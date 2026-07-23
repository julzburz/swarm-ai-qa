from __future__ import annotations

import importlib.metadata
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.async_api import Request, Route, async_playwright

from workers.browser.playwright_worker import (
    ensure_safe_runtime_destination,
    resource_url_is_allowed,
    url_is_allowed,
)

from .models import (
    AccessibilityPageScanV1,
    AccessibilityWorkerRequestV1,
    AccessibilityWorkerResultV1,
)


class PlaywrightAxeWorker:
    """Navigate allowlisted pages and run axe without mutating target state."""

    def __init__(
        self,
        artifact_root: str | Path = ".data/artifacts",
        *,
        axe_script_path: str | Path | None = None,
        headless: bool = True,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.configured_axe_script_path = axe_script_path
        self.headless = headless

    async def run(
        self,
        request: AccessibilityWorkerRequestV1,
    ) -> AccessibilityWorkerResultV1:
        base_url = str(request.base_url)
        await ensure_safe_runtime_destination(
            base_url,
            allow_private_network=request.allow_private_network,
        )
        axe_script_path = _resolve_axe_script(
            self.configured_axe_script_path
        )
        task_dir = (
            self.artifact_root
            / str(request.run_id)
            / str(request.task_id)
            / "accessibility"
        )
        task_dir.mkdir(parents=True, exist_ok=True)
        report_path = task_dir / "axe-results.json"
        request_count = 0
        blocked_requests: list[str] = []
        pages: list[AccessibilityPageScanV1] = []

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            browser_version = browser.version
            context = await browser.new_context(service_workers="block")
            context.set_default_timeout(request.timeout_seconds * 1000)
            context.set_default_navigation_timeout(request.timeout_seconds * 1000)

            async def guard(route: Route, intercepted: Request) -> None:
                nonlocal request_count
                request_count += 1
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
                    blocked_requests.append(_safe_url(intercepted.url))
                    await route.abort("blockedbyclient")

            await context.route("**/*", guard)
            page = await context.new_page()
            try:
                for path in _unique_paths(request.allowed_paths):
                    pages.append(
                        await self._scan_page(
                            page,
                            base_url,
                            path,
                            request.wcag_tags,
                            axe_script_path,
                        )
                    )
            finally:
                await context.close()
                await browser.close()

        axe_version = _axe_version(pages)
        result = AccessibilityWorkerResultV1(
            pages=pages,
            report_path=str(report_path.resolve()),
            request_count=request_count,
            blocked_requests=sorted(set(blocked_requests)),
            playwright_version=importlib.metadata.version("playwright"),
            browser_version=browser_version,
            axe_version=axe_version,
            wcag_tags=request.wcag_tags,
        )
        report_path.write_text(
            result.model_dump_json(
                indent=2,
                exclude={"report_path"},
            ),
            encoding="utf-8",
        )
        return result

    async def _scan_page(
        self,
        page,
        base_url: str,
        path: str,
        wcag_tags: list[str],
        axe_script_path: Path,
    ) -> AccessibilityPageScanV1:
        started = time.monotonic()
        target = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        response = await page.goto(target, wait_until="load")
        await page.add_script_tag(path=str(axe_script_path))
        raw = await page.evaluate(
            """
            async (tags) => {
              const results = await window.axe.run(document, {
                runOnly: { type: "tag", values: tags },
                resultTypes: ["violations", "passes", "incomplete", "inapplicable"],
              });
              return {
                axeVersion: window.axe.version,
                violations: results.violations.map((violation) => ({
                  rule_id: violation.id,
                  impact: violation.impact,
                  description: violation.description,
                  help: violation.help,
                  help_url: violation.helpUrl,
                  tags: violation.tags,
                  nodes: violation.nodes.map((node) => ({
                    target: node.target.map((item) =>
                      Array.isArray(item) ? item.join(" > ") : String(item)
                    ),
                    failure_summary: node.failureSummary || violation.help,
                  })),
                })),
                passes: results.passes.length,
                incomplete: results.incomplete.length,
                inapplicable: results.inapplicable.length,
              };
            }
            """,
            wcag_tags,
        )
        raw["violations"] = _redact_violations(raw["violations"])
        rules_run = (
            len(raw["violations"])
            + raw["passes"]
            + raw["incomplete"]
            + raw["inapplicable"]
        )
        page_scan = AccessibilityPageScanV1(
            path=path,
            final_url=_safe_url(page.url),
            http_status=response.status if response is not None else None,
            title=await page.title(),
            axe_version=str(raw["axeVersion"]),
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
            rules_run=rules_run,
            passes=raw["passes"],
            incomplete=raw["incomplete"],
            inapplicable=raw["inapplicable"],
            violations=raw["violations"],
        )
        return page_scan


def _resolve_axe_script(configured: str | Path | None) -> Path:
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(os.environ["SWARM_AXE_SCRIPT_PATH"]).expanduser()
        if os.getenv("SWARM_AXE_SCRIPT_PATH")
        else None,
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "node_modules"
        / "axe-core"
        / "axe.min.js",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(
        "axe-core script not found; run npm install in frontend or set "
        "SWARM_AXE_SCRIPT_PATH"
    )


def _axe_version(pages: list[AccessibilityPageScanV1]) -> str:
    if not pages:
        return "unknown"
    return pages[0].axe_version


def _redact_violations(violations: list[dict]) -> list[dict]:
    for violation in violations:
        for node in violation.get("nodes", []):
            node["target"] = [
                _bounded_text(str(target), 500)
                for target in node.get("target", [])
            ]
            node["failure_summary"] = _bounded_text(
                str(node.get("failure_summary", violation.get("help", "Violation"))),
                1000,
            )
    return violations


def _bounded_text(value: str, limit: int) -> str:
    bounded = value.replace("\r", " ").replace("\n", " ")[:limit]
    return re.sub(
        r"(?i)\b(token|password|secret|authorization|api[_-]?key)\b"
        r"\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        bounded,
    )


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _unique_paths(paths: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            "/" + path.strip("/") if path != "/" else "/"
            for path in paths
        )
    )
