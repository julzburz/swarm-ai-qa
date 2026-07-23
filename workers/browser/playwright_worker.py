from __future__ import annotations

import asyncio
import importlib.metadata
import re
import socket
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.async_api import (
    Request,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from schemas.common import is_forbidden_network_host

from .models import (
    BrowserInteractionStepCaptureV1,
    BrowserJourneyCaptureV1,
    BrowserWorkerRequestV1,
    BrowserWorkerResultV1,
)


SENSITIVE_ACTION_PATTERN = re.compile(
    r"(?i)\b(delete|remove|destroy|purchase|buy|pay|checkout|place\s+order|"
    r"log\s*out|logout|sign\s*out|unsubscribe|cancel\s+account|admin|"
    r"transfer|withdraw|send\s+money|confirm)\b"
)
SENSITIVE_FIELD_PATTERN = re.compile(
    r"(?i)\b(password|passcode|credential|token|secret|csrf|session|card|"
    r"cvv|cvc|iban|account|ssn|social|document|dni)\b"
)
SAFE_INPUT_TYPES = {"text", "search", "email", "tel", "url", "number"}


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
        blocked_interactions: list[str] = []
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
                            interaction_mode=request.interaction_mode,
                            allow_get_form_submission=(
                                request.allow_get_form_submission
                            ),
                            max_interactions=(
                                request.max_interactions_per_path
                            ),
                            allowed_paths=request.allowed_paths,
                            blocked_paths=request.blocked_paths,
                            blocked_interactions=blocked_interactions,
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
            blocked_interactions=sorted(set(blocked_interactions)),
            interaction_mode=request.interaction_mode,
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
        *,
        interaction_mode: str,
        allow_get_form_submission: bool,
        max_interactions: int,
        allowed_paths: list[str],
        blocked_paths: list[str],
        blocked_interactions: list[str],
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
        interaction_steps: list[BrowserInteractionStepCaptureV1] = []
        try:
            response = await page.goto(target, wait_until="load")
            http_status = response.status if response is not None else None
            final_url = page.url
            title = await page.title()
            if http_status is not None and http_status >= 400:
                status = "failed"
            if len(page_errors) > page_error_start:
                status = "failed"
            if (
                status == "passed"
                and interaction_mode == "safe_staging"
                and max_interactions > 0
            ):
                interaction_steps = await _run_safe_interactions(
                    page,
                    target,
                    base_url,
                    allowed_paths,
                    blocked_paths,
                    allow_get_form_submission=allow_get_form_submission,
                    max_interactions=max_interactions,
                    blocked_interactions=blocked_interactions,
                )
                final_url = page.url
                title = await page.title()
                if any(
                    step.status == "failed"
                    for step in interaction_steps
                ):
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
            interaction_steps=interaction_steps,
        )


async def _run_safe_interactions(
    page,
    initial_url: str,
    base_url: str,
    allowed_paths: list[str],
    blocked_paths: list[str],
    *,
    allow_get_form_submission: bool,
    max_interactions: int,
    blocked_interactions: list[str],
) -> list[BrowserInteractionStepCaptureV1]:
    steps: list[BrowserInteractionStepCaptureV1] = []
    action_count = 0
    link = await _find_safe_link(
        page,
        base_url,
        allowed_paths,
        blocked_paths,
        blocked_interactions,
    )
    if link is not None and action_count < max_interactions:
        locator, destination, label = link
        started = time.monotonic()
        try:
            await locator.click()
            try:
                await page.wait_for_load_state("domcontentloaded")
            except PlaywrightTimeoutError:
                pass
            final_url = page.url
            destination_allowed = url_is_allowed(
                final_url,
                base_url,
                allowed_paths,
                blocked_paths,
            )
            status = "passed" if destination_allowed else "blocked"
            observation = (
                "El enlace interno autorizado respondió y permaneció dentro "
                "del origen y rutas permitidas."
                if destination_allowed
                else "La interacción intentó salir del destino autorizado."
            )
        except Exception as exc:
            status = (
                "blocked"
                if "ERR_BLOCKED_BY_CLIENT" in str(exc)
                else "failed"
            )
            final_url = page.url or initial_url
            observation = _redact_text(
                f"{type(exc).__name__}: {exc}"
            )
        steps.append(
            BrowserInteractionStepCaptureV1(
                action="click_safe_link",
                status=status,
                target=label,
                observation=observation,
                final_url=_safe_url(final_url),
                duration_ms=max(
                    0,
                    round((time.monotonic() - started) * 1000),
                ),
            )
        )
        action_count += 1
        if status == "passed":
            steps.append(
                BrowserInteractionStepCaptureV1(
                    action="assert_safe_destination",
                    status="passed",
                    target=_safe_url(destination),
                    observation=(
                        "La navegación resultante coincide con un destino "
                        "same-origin incluido en el allowlist."
                    ),
                    final_url=_safe_url(page.url),
                    duration_ms=0,
                )
            )
        try:
            await page.goto(initial_url, wait_until="load")
        except Exception as exc:
            steps.append(
                BrowserInteractionStepCaptureV1(
                    action="assert_safe_destination",
                    status="failed",
                    target=_safe_url(initial_url),
                    observation=_redact_text(
                        f"No se pudo restaurar la ruta inicial: {exc}"
                    ),
                    final_url=_safe_url(page.url or initial_url),
                    duration_ms=0,
                )
            )
            return steps

    if (
        allow_get_form_submission
        and action_count < max_interactions
    ):
        form = await _find_safe_get_form(
            page,
            base_url,
            allowed_paths,
            blocked_paths,
            blocked_interactions,
        )
        if form is not None:
            form_locator, _, form_label = form
            inputs = form_locator.locator("input[name], textarea[name]")
            input_count = min(await inputs.count(), 20)
            filled = 0
            for index in range(input_count):
                if action_count >= max_interactions - 1:
                    break
                field = inputs.nth(index)
                field_type = (
                    (await field.get_attribute("type")) or "text"
                ).lower()
                name = (
                    (await field.get_attribute("name"))
                    or (await field.get_attribute("aria-label"))
                    or f"field-{index + 1}"
                )
                if (
                    field_type not in SAFE_INPUT_TYPES
                    or SENSITIVE_FIELD_PATTERN.search(name)
                    or not await field.is_visible()
                    or not await field.is_enabled()
                ):
                    if SENSITIVE_FIELD_PATTERN.search(name):
                        blocked_interactions.append(
                            f"field:{_redact_text(name)[:80]}"
                        )
                    continue
                started = time.monotonic()
                try:
                    await field.fill(_synthetic_value(field_type))
                    status = "passed"
                    observation = (
                        "Campo seguro completado con un valor sintético; "
                        "no se utilizaron datos personales ni secretos."
                    )
                    filled += 1
                except Exception as exc:
                    status = "failed"
                    observation = _redact_text(
                        f"{type(exc).__name__}: {exc}"
                    )
                steps.append(
                    BrowserInteractionStepCaptureV1(
                        action="fill_safe_field",
                        status=status,
                        target=_redact_text(name)[:120],
                        observation=observation,
                        final_url=_safe_url(page.url),
                        duration_ms=max(
                            0,
                            round((time.monotonic() - started) * 1000),
                        ),
                    )
                )
                action_count += 1

            if filled and action_count < max_interactions:
                started = time.monotonic()
                try:
                    await form_locator.evaluate(
                        "(form) => form.requestSubmit()"
                    )
                    try:
                        await page.wait_for_load_state("domcontentloaded")
                    except PlaywrightTimeoutError:
                        pass
                    destination_allowed = url_is_allowed(
                        page.url,
                        base_url,
                        allowed_paths,
                        blocked_paths,
                    )
                    status = (
                        "passed" if destination_allowed else "blocked"
                    )
                    observation = (
                        "Formulario GET autorizado enviado con datos "
                        "sintéticos y destino permitido."
                        if destination_allowed
                        else "El formulario intentó salir del destino autorizado."
                    )
                except Exception as exc:
                    status = (
                        "blocked"
                        if "ERR_BLOCKED_BY_CLIENT" in str(exc)
                        else "failed"
                    )
                    observation = _redact_text(
                        f"{type(exc).__name__}: {exc}"
                    )
                steps.append(
                    BrowserInteractionStepCaptureV1(
                        action="submit_safe_get_form",
                        status=status,
                        target=form_label,
                        observation=observation,
                        final_url=_safe_url(page.url),
                        duration_ms=max(
                            0,
                            round((time.monotonic() - started) * 1000),
                        ),
                    )
                )
    return steps


async def _find_safe_link(
    page,
    base_url: str,
    allowed_paths: list[str],
    blocked_paths: list[str],
    blocked_interactions: list[str],
):
    links = page.locator("a[href]")
    selected = None
    for index in range(min(await links.count(), 50)):
        link = links.nth(index)
        href = await link.get_attribute("href")
        if not href or await link.get_attribute("download") is not None:
            continue
        if (await link.get_attribute("target") or "").lower() == "_blank":
            continue
        destination = urljoin(page.url, href)
        label = _redact_text(
            ((await link.inner_text()) or href).strip()
        )[:120]
        descriptor = f"{label} {_safe_url(destination)}"
        if SENSITIVE_ACTION_PATTERN.search(descriptor):
            blocked_interactions.append(
                f"link:{_safe_url(destination)}"
            )
            continue
        if not url_is_allowed(
            destination,
            base_url,
            allowed_paths,
            blocked_paths,
        ):
            blocked_interactions.append(
                f"link:{_safe_url(destination)}"
            )
            continue
        if _safe_url(destination) == _safe_url(page.url):
            continue
        if selected is None:
            selected = (link, destination, label)
    return selected


async def _find_safe_get_form(
    page,
    base_url: str,
    allowed_paths: list[str],
    blocked_paths: list[str],
    blocked_interactions: list[str],
):
    forms = page.locator("form")
    selected = None
    for index in range(min(await forms.count(), 20)):
        form = forms.nth(index)
        method = ((await form.get_attribute("method")) or "get").lower()
        action = await form.get_attribute("action") or page.url
        action_url = urljoin(page.url, action)
        label = _redact_text(
            ((await form.inner_text()) or "GET form").strip()
        )[:120]
        descriptor = f"{label} {_safe_url(action_url)}"
        if method != "get":
            blocked_interactions.append(
                f"form:{method.upper()}:{_safe_url(action_url)}"
            )
            continue
        if await _form_has_sensitive_controls(form):
            blocked_interactions.append(
                f"form:sensitive:{_safe_url(action_url)}"
            )
            continue
        if SENSITIVE_ACTION_PATTERN.search(descriptor):
            blocked_interactions.append(
                f"form:GET:{_safe_url(action_url)}"
            )
            continue
        if not url_is_allowed(
            action_url,
            base_url,
            allowed_paths,
            blocked_paths,
        ):
            blocked_interactions.append(
                f"form:GET:{_safe_url(action_url)}"
            )
            continue
        if selected is None:
            selected = (
                form,
                action_url,
                label or _safe_url(action_url),
            )
    return selected


async def _form_has_sensitive_controls(form) -> bool:
    controls = form.locator("input, textarea, select, button")
    for index in range(min(await controls.count(), 50)):
        control = controls.nth(index)
        control_type = (
            (await control.get_attribute("type")) or ""
        ).lower()
        descriptor = " ".join(
            filter(
                None,
                [
                    await control.get_attribute("name"),
                    await control.get_attribute("id"),
                    await control.get_attribute("aria-label"),
                    await control.get_attribute("placeholder"),
                    await control.get_attribute("formaction"),
                    (await control.inner_text()).strip(),
                ],
            )
        )
        if (
            control_type in {"password", "file"}
            or SENSITIVE_FIELD_PATTERN.search(descriptor)
            or SENSITIVE_ACTION_PATTERN.search(descriptor)
        ):
            return True
        if control_type == "hidden" and await control.get_attribute("value"):
            return True
        form_method = (
            await control.get_attribute("formmethod")
        )
        if form_method and form_method.lower() != "get":
            return True
    return False


def _synthetic_value(field_type: str) -> str:
    return {
        "email": "qa.synthetic@example.invalid",
        "tel": "000000000",
        "url": "https://example.invalid",
        "number": "1",
        "search": "swarm qa safe test",
    }.get(field_type, "swarm qa synthetic value")


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
