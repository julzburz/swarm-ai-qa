from __future__ import annotations

import importlib.metadata
import json
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
    PerformanceSampleV1,
    PerformanceWorkerRequestV1,
    PerformanceWorkerResultV1,
)


VITALS_INIT_SCRIPT = """
(() => {
  window.__swarmPerformanceVitals = { lcp: null, cls: 0 };
  try {
    new PerformanceObserver((list) => {
      const entries = list.getEntries();
      const last = entries[entries.length - 1];
      if (last) window.__swarmPerformanceVitals.lcp = last.startTime;
    }).observe({ type: "largest-contentful-paint", buffered: true });
  } catch (_) {}
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) {
          window.__swarmPerformanceVitals.cls += entry.value;
        }
      }
    }).observe({ type: "layout-shift", buffered: true });
  } catch (_) {}
})();
"""


class PlaywrightPerformanceWorker:
    """Cold-context, single-user lab measurements with bounded read-only traffic."""

    def __init__(
        self,
        artifact_root: str | Path = ".data/artifacts",
        *,
        headless: bool = True,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.headless = headless

    async def run(
        self,
        request: PerformanceWorkerRequestV1,
    ) -> PerformanceWorkerResultV1:
        base_url = str(request.base_url)
        await ensure_safe_runtime_destination(
            base_url,
            allow_private_network=request.allow_private_network,
        )
        task_dir = (
            self.artifact_root
            / str(request.run_id)
            / str(request.task_id)
            / "performance"
        )
        task_dir.mkdir(parents=True, exist_ok=True)
        report_path = task_dir / "performance-smoke-results.json"
        request_count = 0
        blocked_requests: list[str] = []
        samples: list[PerformanceSampleV1] = []

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            browser_version = browser.version
            try:
                for path in _unique_paths(request.allowed_paths):
                    for repetition in range(1, request.repetitions + 1):
                        context = await browser.new_context(
                            service_workers="block",
                            viewport={"width": 1365, "height": 768},
                        )
                        context.set_default_timeout(
                            request.timeout_seconds * 1000
                        )
                        context.set_default_navigation_timeout(
                            request.timeout_seconds * 1000
                        )
                        await context.add_init_script(
                            script=VITALS_INIT_SCRIPT
                        )

                        async def guard(
                            route: Route,
                            intercepted: Request,
                        ) -> None:
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
                                blocked_requests.append(
                                    _safe_url(intercepted.url)
                                )
                                await route.abort("blockedbyclient")

                        await context.route("**/*", guard)
                        page = await context.new_page()
                        try:
                            samples.append(
                                await self._measure(
                                    page,
                                    base_url,
                                    path,
                                    repetition,
                                )
                            )
                        finally:
                            await context.close()
            finally:
                await browser.close()

        result = PerformanceWorkerResultV1(
            samples=samples,
            report_path=str(report_path.resolve()),
            request_count=request_count,
            blocked_requests=sorted(set(blocked_requests)),
            playwright_version=importlib.metadata.version("playwright"),
            browser_version=browser_version,
        )
        report_path.write_text(
            json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return result

    async def _measure(
        self,
        page,
        base_url: str,
        path: str,
        repetition: int,
    ) -> PerformanceSampleV1:
        target = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        started = time.monotonic()
        status = "passed"
        http_status: int | None = None
        final_url = target
        metrics: dict = {}
        error: str | None = None
        try:
            response = await page.goto(target, wait_until="load")
            http_status = response.status if response is not None else None
            final_url = page.url
            if http_status is not None and http_status >= 400:
                status = "failed"
            await page.wait_for_timeout(250)
            metrics = await page.evaluate(
                """
                () => {
                  const navigation = performance.getEntriesByType("navigation")[0];
                  const resources = performance.getEntriesByType("resource");
                  const fcp = performance.getEntriesByName("first-contentful-paint")[0];
                  const vitals = window.__swarmPerformanceVitals || {};
                  if (!navigation) return {};
                  return {
                    ttfb: navigation.responseStart - navigation.startTime,
                    domContentLoaded:
                      navigation.domContentLoadedEventEnd - navigation.startTime,
                    loadEvent: navigation.loadEventEnd - navigation.startTime,
                    fcp: fcp ? fcp.startTime : null,
                    lcp: vitals.lcp ?? null,
                    cls: vitals.cls ?? null,
                    transferBytes:
                      navigation.transferSize +
                      resources.reduce(
                        (total, resource) => total + resource.transferSize,
                        0,
                      ),
                    resourceCount: resources.length + 1,
                  };
                }
                """
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            error = message.replace("\r", " ").replace("\n", " ")[:1000]
            status = (
                "blocked"
                if "ERR_BLOCKED_BY_CLIENT" in message
                else "failed"
            )
            final_url = page.url or target

        return PerformanceSampleV1(
            path=path,
            final_url=_safe_url(final_url),
            repetition=repetition,
            http_status=http_status,
            status=status,
            ttfb_ms=_optional_float(metrics.get("ttfb")),
            dom_content_loaded_ms=_optional_float(
                metrics.get("domContentLoaded")
            ),
            load_event_ms=_optional_float(metrics.get("loadEvent")),
            first_contentful_paint_ms=_optional_float(metrics.get("fcp")),
            largest_contentful_paint_ms=_optional_float(metrics.get("lcp")),
            cumulative_layout_shift=_optional_float(metrics.get("cls")),
            transfer_bytes=_optional_int(metrics.get("transferBytes")),
            resource_count=_optional_int(metrics.get("resourceCount")),
            duration_ms=max(
                0,
                round((time.monotonic() - started) * 1000),
            ),
            error=error,
        )


def _optional_float(value) -> float | None:
    return max(0.0, float(value)) if value is not None else None


def _optional_int(value) -> int | None:
    return max(0, int(value)) if value is not None else None


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))


def _unique_paths(paths: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            "/" + path.strip("/") if path != "/" else "/"
            for path in paths
        )
    )
