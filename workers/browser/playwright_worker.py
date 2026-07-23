from __future__ import annotations

import asyncio
import importlib.metadata
import re
import socket
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.async_api import Request, Route, async_playwright

from schemas.common import is_forbidden_network_host

from .models import BrowserJourneyCaptureV1, BrowserWorkerRequestV1, BrowserWorkerResultV1


class PlaywrightBrowserWorker:
    """Single-browser, read-only worker with origin, route and request budgets."""

    def __init__(self, artifact_root: str | Path = ".data/artifacts", *, headless: bool = True) -> None:
        self.artifact_root = Path(artifact_root)
        self.headless = headless

    async def run(self, request: BrowserWorkerRequestV1) -> BrowserWorkerResultV1:
        base_url = str(request.base_url)
        await ensure_safe_runtime_destination(
            base_url,
            allow_private_network=request.allow_private_network,
        )
        task_dir = self.artifact_root / str(request.run_id) / str(request.task_id) / "browser"
        task_dir.mkdir(parents=True, exist_ok=True)
        trace_path = task_dir / "trace.zip"
        request_count = 0
        blocked_requests: list[str] = []
        captures: list[BrowserJourneyCaptureV1] = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            browser_version = browser.version
            context = await browser.new_context(service_workers="block")
            context.set_default_timeout(request.timeout_seconds * 1000)
            context.set_default_navigation_timeout(request.timeout_seconds * 1000)

            async def guard(route: Route, intercepted: Request) -> None:
                nonlocal request_count
                request_count += 1
                safe_url = _safe_url(intercepted.url)
                target_allowed = (
                    url_is_allowed(
                        intercepted.url,
                        base_url,
                        request.allowed_paths,
                        request.blocked_paths,
                    )
                    if intercepted.is_navigation_request()
                    else resource_url_is_allowed(
                        intercepted.url,
                        base_url,
                        request.blocked_paths,
                    )
                )
                allowed = (
                    request_count <= request.max_requests
                    and intercepted.method in {"GET", "HEAD"}
                    and target_allowed
                )
                if allowed:
                    await route.continue_()
                else:
                    blocked_requests.append(safe_url)
                    await route.abort("blockedbyclient")

            await context.route("**/*", guard)
            await context.tracing.start(screenshots=True, snapshots=True, sources=False)
            page = await context.new_page()
            console_errors: list[str] = []
            page_errors: list[str] = []
            request_failures: list[str] = []
            page.on(
                "console",
                lambda message: console_errors.append(_redact_text(message.text))
                if message.type == "error"
                else None,
            )
            page.on("pageerror", lambda error: page_errors.append(_redact_text(str(error))))
            page.on(
                "requestfailed",
                lambda failed: request_failures.append(
                    f"{_safe_url(failed.url)}: {_redact_text(str(failed.failure or 'request failed'))}"
                ),
            )

            try:
                for index, path in enumerate(_unique_paths(request.allowed_paths), start=1):
                    captures.append(
                        await self._navigate(
                            page,
                            base_url,
                            path,
                            task_dir / f"journey-{index}.png",
                            console_errors,
                            page_errors,
                            request_failures,
                        )
                    )
            finally:
                await context.tracing.stop(path=trace_path)
                await context.close()
                await browser.close()

        return BrowserWorkerResultV1(
            journeys=captures,
            trace_path=str(trace_path.resolve()),
            request_count=request_count,
            blocked_requests=sorted(set(blocked_requests)),
            playwright_version=importlib.metadata.version("playwright"),
            browser_version=browser_version,
        )

    async def _navigate(
        self,
        page,
        base_url: str,
        path: str,
        screenshot_path: Path,
        console_errors: list[str],
        page_errors: list[str],
        request_failures: list[str],
    ) -> BrowserJourneyCaptureV1:
        started = time.monotonic()
        console_start = len(console_errors)
        page_error_start = len(page_errors)
        failure_start = len(request_failures)
        target = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        http_status: int | None = None
        status = "passed"
        title = ""
        final_url = target
        try:
            response = await page.goto(target, wait_until="load")
            http_status = response.status if response is not None else None
            final_url = page.url
            title = await page.title()
            if http_status is not None and http_status >= 400:
                status = "failed"
            if len(page_errors) > page_error_start:
                status = "failed"
        except Exception as exc:  # Playwright boundary
            status = "blocked" if "ERR_BLOCKED_BY_CLIENT" in str(exc) else "failed"
            page_errors.append(_redact_text(f"{type(exc).__name__}: {exc}"))
            final_url = page.url or target
        screenshot: str | None = None
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
            screenshot = str(screenshot_path.resolve())
        except Exception as exc:  # evidence capture boundary
            page_errors.append(_redact_text(f"ScreenshotError: {exc}"))
            status = "failed"
        return BrowserJourneyCaptureV1(
            name=f"Navigate {path}",
            path=path,
            final_url=_safe_url(final_url),
            status=status,
            http_status=http_status,
            title=title,
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
            screenshot_path=screenshot,
            console_errors=console_errors[console_start:],
            page_errors=page_errors[page_error_start:],
            request_failures=request_failures[failure_start:],
        )


def url_is_allowed(
    candidate: str,
    base_url: str,
    allowed_paths: list[str],
    blocked_paths: list[str],
) -> bool:
    candidate_parts = urlsplit(candidate)
    base_parts = urlsplit(base_url)
    if _origin(candidate_parts) != _origin(base_parts):
        return False
    path = candidate_parts.path or "/"
    if any(_path_matches(path, blocked) for blocked in blocked_paths):
        return False
    return any(_path_matches(path, allowed) for allowed in allowed_paths)


def resource_url_is_allowed(
    candidate: str,
    base_url: str,
    blocked_paths: list[str],
) -> bool:
    """Allow same-origin resources without treating navigation paths as asset paths."""

    candidate_parts = urlsplit(candidate)
    base_parts = urlsplit(base_url)
    if _origin(candidate_parts) != _origin(base_parts):
        return False
    path = candidate_parts.path or "/"
    return not any(_path_matches(path, blocked) for blocked in blocked_paths)


async def ensure_safe_runtime_destination(
    url: str,
    *,
    allow_private_network: bool = False,
) -> None:
    """Fail closed when a browser target resolves to a non-public address."""

    if allow_private_network:
        return
    parts = urlsplit(url)
    host = parts.hostname or ""
    if is_forbidden_network_host(host):
        raise ValueError("Browser target resolves to a forbidden network address")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            parts.port or (443 if parts.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("Browser target hostname could not be resolved safely") from exc
    resolved_hosts = {item[4][0] for item in addresses}
    if not resolved_hosts or any(
        is_forbidden_network_host(address) for address in resolved_hosts
    ):
        raise ValueError("Browser target resolves to a forbidden network address")


def _origin(parts) -> tuple[str, str, int | None]:
    default_port = 443 if parts.scheme.lower() == "https" else 80 if parts.scheme.lower() == "http" else None
    return parts.scheme.lower(), (parts.hostname or "").lower(), parts.port or default_port


def _path_matches(path: str, configured: str) -> bool:
    prefix = "/" + configured.strip("/")
    if prefix == "/":
        return True
    return path == prefix or path.startswith(prefix + "/")


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _redact_text(value: str) -> str:
    bounded = value.replace("\r", " ").replace("\n", " ")[:1000]
    return re.sub(
        r"(?i)\b(token|password|secret|authorization|api[_-]?key)\b\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        bounded,
    )


def _unique_paths(paths: list[str]) -> list[str]:
    return list(dict.fromkeys("/" + path.strip("/") if path != "/" else "/" for path in paths))
