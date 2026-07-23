from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from schemas.common import MissionMode, RuntimeTargetV1
from workers.browser.playwright_worker import (
    ensure_safe_runtime_destination,
    url_is_allowed,
)

from .schemas import RuntimeReconnaissanceV1


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a":
            return
        href = next(
            (value for name, value in attrs if name.lower() == "href"),
            None,
        )
        if href:
            self.links.append(href)


async def inspect_runtime(
    target: RuntimeTargetV1,
    mode: MissionMode,
) -> RuntimeReconnaissanceV1:
    base_url = str(target.base_url)
    await ensure_safe_runtime_destination(base_url)
    max_paths = {
        MissionMode.QUICK_TASK: 1,
        MissionMode.TARGETED_EXAMINATION: 5,
        MissionMode.FULL_EXAMINATION: 10,
    }[mode]
    seed_paths = _unique_paths(target.allowed_paths)
    discovered = list(seed_paths)
    notes: list[str] = []
    status_code: int | None = None
    openapi_path: str | None = None
    content_type: str | None = None

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        follow_redirects=False,
        headers={"User-Agent": "Swarm-AI-QA-Reconnaissance/1.0"},
    ) as client:
        try:
            response = await client.get(_target_url(base_url, seed_paths[0]))
            status_code = response.status_code
            content_type = response.headers.get("content-type")
            if 300 <= response.status_code < 400:
                notes.append(
                    "La URL inicial respondió con una redirección; no se "
                    "siguió automáticamente durante el reconocimiento."
                )
            if "text/html" in (content_type or "").lower():
                parser = _LinkParser()
                parser.feed(response.text[:1_000_000])
                for href in parser.links:
                    candidate = _safe_same_origin_path(base_url, href)
                    if (
                        candidate is not None
                        and url_is_allowed(
                            _target_url(base_url, candidate),
                            base_url,
                            target.allowed_paths,
                            target.blocked_paths,
                        )
                        and candidate not in discovered
                    ):
                        discovered.append(candidate)
                    if len(discovered) >= max_paths:
                        break
            else:
                notes.append(
                    "La respuesta inicial no fue HTML; no se descubrieron "
                    "enlaces de navegación."
                )
        except (httpx.HTTPError, ValueError) as exc:
            notes.append(
                f"El reconocimiento HTTP inicial no pudo completarse: "
                f"{type(exc).__name__}."
            )

        if mode != MissionMode.QUICK_TASK:
            contract_candidates = [
                path
                for path in [
                    *discovered,
                    "/openapi.json",
                    "/api/openapi.json",
                    "/control-plane/openapi.json",
                ]
                if path.endswith((".json", "/docs"))
                and url_is_allowed(
                    _target_url(base_url, path),
                    base_url,
                    target.allowed_paths,
                    target.blocked_paths,
                )
            ]
            for path in _unique_paths(contract_candidates)[:4]:
                try:
                    response = await client.get(_target_url(base_url, path))
                    if response.status_code != 200:
                        continue
                    payload = response.json()
                    if (
                        isinstance(payload, dict)
                        and isinstance(payload.get("openapi"), str)
                    ):
                        openapi_path = path
                        if path not in discovered:
                            discovered.append(path)
                        break
                except (httpx.HTTPError, ValueError):
                    continue

    planned = discovered[:max_paths]
    if (
        openapi_path is not None
        and openapi_path not in planned
        and planned
    ):
        planned[-1] = openapi_path
    return RuntimeReconnaissanceV1(
        base_url=target.base_url,
        reachable=status_code is not None and status_code < 500,
        status_code=status_code,
        content_type=content_type,
        discovered_paths=discovered,
        planned_paths=planned,
        openapi_path=openapi_path,
        notes=notes,
    )


def _target_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _safe_same_origin_path(
    base_url: str,
    href: str,
) -> str | None:
    absolute = urljoin(base_url, href)
    base = urlsplit(base_url)
    candidate = urlsplit(absolute)
    if (
        candidate.scheme not in {"http", "https"}
        or candidate.scheme != base.scheme
        or candidate.netloc != base.netloc
    ):
        return None
    path = candidate.path or "/"
    return urlunsplit(("", "", path, "", ""))


def _unique_paths(paths: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            "/" + path.strip("/") if path != "/" else "/"
            for path in paths
        )
    )
