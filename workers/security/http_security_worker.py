from __future__ import annotations

import asyncio
import importlib.metadata
import json
import ssl
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from schemas.common import Severity
from workers.browser.playwright_worker import (
    ensure_safe_runtime_destination,
    url_is_allowed,
)

from .models import (
    CookieObservationV1,
    SecurityPageAuditV1,
    SecuritySignalV1,
    SecurityWorkerRequestV1,
    SecurityWorkerResultV1,
    TlsObservationV1,
)


AUDITED_HEADERS = {
    "access-control-allow-credentials",
    "access-control-allow-origin",
    "content-security-policy",
    "content-type",
    "permissions-policy",
    "referrer-policy",
    "server",
    "strict-transport-security",
    "x-content-type-options",
    "x-frame-options",
    "x-powered-by",
}
MAX_REDIRECTS = 5


class PassiveHttpSecurityWorker:
    """Inspect explicitly allowlisted responses without payloads or exploitation."""

    def __init__(self, artifact_root: str | Path = ".data/artifacts") -> None:
        self.artifact_root = Path(artifact_root)

    async def run(
        self,
        request: SecurityWorkerRequestV1,
    ) -> SecurityWorkerResultV1:
        base_url = str(request.base_url)
        await ensure_safe_runtime_destination(
            base_url,
            allow_private_network=request.allow_private_network,
        )
        task_dir = (
            self.artifact_root
            / str(request.run_id)
            / str(request.task_id)
            / "security"
        )
        task_dir.mkdir(parents=True, exist_ok=True)
        report_path = task_dir / "passive-security-results.json"
        pages: list[SecurityPageAuditV1] = []
        request_count = 0
        timeout = httpx.Timeout(request.timeout_seconds)

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": "Swarm-AI-QA-Passive-Security/1.0"},
        ) as client:
            for path in _unique_paths(request.allowed_paths):
                remaining = request.max_requests - request_count
                if remaining <= 0:
                    raise ValueError("Passive security request budget exhausted")
                page, consumed = await self._audit_path(
                    client,
                    request,
                    path,
                    remaining,
                )
                pages.append(page)
                request_count += consumed

        tls = await _observe_tls(
            base_url,
            allow_private_network=request.allow_private_network,
            timeout_seconds=request.timeout_seconds,
        )
        result = SecurityWorkerResultV1(
            pages=pages,
            tls=tls,
            report_path=str(report_path.resolve()),
            request_count=request_count,
            httpx_version=importlib.metadata.version("httpx"),
        )
        report_path.write_text(
            json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return result

    async def _audit_path(
        self,
        client: httpx.AsyncClient,
        request: SecurityWorkerRequestV1,
        path: str,
        remaining_budget: int,
    ) -> tuple[SecurityPageAuditV1, int]:
        base_url = str(request.base_url)
        current_url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        requested_url = _safe_url(current_url)
        redirects: list[str] = []
        consumed = 0
        started = time.monotonic()
        response: httpx.Response | None = None

        for _ in range(MAX_REDIRECTS + 1):
            if consumed >= remaining_budget:
                raise ValueError("Passive security request budget exhausted")
            await ensure_safe_runtime_destination(
                current_url,
                allow_private_network=request.allow_private_network,
            )
            if not url_is_allowed(
                current_url,
                base_url,
                request.allowed_paths,
                request.blocked_paths,
            ):
                raise ValueError(
                    "Security target redirected outside the authorized origin or route"
                )
            response = await client.send(
                client.build_request("GET", current_url),
                stream=True,
            )
            consumed += 1
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                break
            next_url = urljoin(current_url, location)
            if not url_is_allowed(
                next_url,
                base_url,
                request.allowed_paths,
                request.blocked_paths,
            ):
                raise ValueError(
                    "Security target redirected outside the authorized origin or route"
                )
            redirects.append(_safe_url(next_url))
            current_url = next_url
        else:
            raise ValueError("Security target exceeded the redirect limit")

        if response is None:
            raise RuntimeError("Passive security worker produced no response")
        final_url = _safe_url(str(response.url))
        headers = {
            key: _bounded_header(value)
            for key, value in response.headers.items()
            if key.lower() in AUDITED_HEADERS
        }
        cookies = [
            _parse_cookie(value)
            for value in response.headers.get_list("set-cookie")
        ]
        content_type = response.headers.get("content-type", "")
        signals = _security_signals(final_url, content_type, headers, cookies)
        await response.aclose()
        return (
            SecurityPageAuditV1(
                path=path,
                requested_url=requested_url,
                final_url=final_url,
                http_status=response.status_code,
                content_type=_bounded_header(content_type),
                audited_headers=headers,
                cookies=cookies,
                signals=signals,
                redirects=redirects,
                duration_ms=max(
                    0,
                    round((time.monotonic() - started) * 1000),
                ),
            ),
            consumed,
        )


def _security_signals(
    url: str,
    content_type: str,
    headers: dict[str, str],
    cookies: list[CookieObservationV1],
) -> list[SecuritySignalV1]:
    lowered = {key.lower(): value for key, value in headers.items()}
    scheme = urlsplit(url).scheme.lower()
    is_html = "text/html" in content_type.lower()
    signals: list[SecuritySignalV1] = []

    if scheme != "https":
        signals.append(
            _signal(
                "transport-https",
                "Runtime route is not protected by HTTPS",
                Severity.MEDIUM,
                1.0,
                "The observed final URL uses HTTP.",
                "Traffic can be intercepted or modified in transit outside a trusted local environment.",
                "Serve the route over HTTPS and redirect HTTP traffic to the HTTPS origin.",
                url,
            )
        )
    elif "strict-transport-security" not in lowered:
        signals.append(
            _signal(
                "header-hsts",
                "HSTS is missing on an HTTPS response",
                Severity.MEDIUM,
                0.98,
                "The HTTPS response did not include Strict-Transport-Security.",
                "A first insecure visit can remain exposed to protocol downgrade attacks.",
                "Add an appropriate Strict-Transport-Security policy after confirming every covered host supports HTTPS.",
                url,
            )
        )

    if is_html and "content-security-policy" not in lowered:
        signals.append(
            _signal(
                "header-csp",
                "Content Security Policy is missing",
                Severity.MEDIUM,
                0.98,
                "The HTML response did not include Content-Security-Policy.",
                "The browser lacks this defense-in-depth control against script injection and unsafe resource loading.",
                "Define and test a restrictive Content-Security-Policy for the application.",
                url,
            )
        )
    if "x-content-type-options" not in lowered:
        signals.append(
            _signal(
                "header-nosniff",
                "MIME sniffing protection is missing",
                Severity.LOW,
                0.98,
                "The response did not include X-Content-Type-Options: nosniff.",
                "Browsers may infer a different content type in contexts where MIME confusion is possible.",
                "Return X-Content-Type-Options: nosniff.",
                url,
            )
        )
    if is_html and not _has_frame_protection(lowered):
        signals.append(
            _signal(
                "header-frame-protection",
                "Frame embedding protection is missing",
                Severity.LOW,
                0.95,
                "Neither CSP frame-ancestors nor X-Frame-Options was observed.",
                "Interactive pages may be embeddable by another origin, increasing clickjacking exposure.",
                "Set CSP frame-ancestors and retain X-Frame-Options where legacy browser coverage is required.",
                url,
            )
        )
    if is_html and "referrer-policy" not in lowered:
        signals.append(
            _signal(
                "header-referrer-policy",
                "Explicit Referrer Policy is missing",
                Severity.LOW,
                0.95,
                "The HTML response did not include Referrer-Policy.",
                "URLs or path details may be shared according to browser defaults instead of an application-defined policy.",
                "Set a Referrer-Policy appropriate to the application's cross-origin needs.",
                url,
            )
        )
    if is_html and "permissions-policy" not in lowered:
        signals.append(
            _signal(
                "header-permissions-policy",
                "Permissions Policy is not declared",
                Severity.INFO,
                0.95,
                "The HTML response did not include Permissions-Policy.",
                "Browser features are not explicitly constrained by an application policy.",
                "Declare only the browser features and origins the application requires.",
                url,
            )
        )

    origin = lowered.get("access-control-allow-origin", "").strip()
    credentials = lowered.get(
        "access-control-allow-credentials", ""
    ).strip().lower()
    if origin == "*" and credentials == "true":
        signals.append(
            _signal(
                "cors-wildcard-credentials",
                "Contradictory credentialed CORS policy observed",
                Severity.MEDIUM,
                0.99,
                "The passive response combined Access-Control-Allow-Origin: * with Access-Control-Allow-Credentials: true.",
                "Browsers reject this combination, so credentialed cross-origin clients can fail and the intended trust boundary is ambiguous.",
                "Return an explicit allowlisted origin for credentialed requests and vary the response by Origin.",
                url,
            )
        )

    for cookie in cookies:
        if not cookie.secure:
            signals.append(
                _signal(
                    "cookie-secure",
                    f"Cookie {cookie.name} lacks Secure",
                    Severity.MEDIUM,
                    0.99,
                    f"The Set-Cookie metadata for {cookie.name} did not include Secure; its value was redacted.",
                    "The cookie may be transmitted over an insecure connection.",
                    "Set Secure and deliver the cookie only from HTTPS.",
                    url,
                )
            )
        if not cookie.http_only:
            signals.append(
                _signal(
                    "cookie-httponly",
                    f"Cookie {cookie.name} lacks HttpOnly",
                    Severity.LOW,
                    0.95,
                    f"The Set-Cookie metadata for {cookie.name} did not include HttpOnly; its value was redacted.",
                    "If the cookie carries a session or other sensitive value, client-side script can access it.",
                    "Set HttpOnly for every cookie that does not require JavaScript access.",
                    url,
                )
            )
        if cookie.same_site is None:
            signals.append(
                _signal(
                    "cookie-samesite",
                    f"Cookie {cookie.name} has no explicit SameSite policy",
                    Severity.LOW,
                    0.95,
                    f"The Set-Cookie metadata for {cookie.name} omitted SameSite; its value was redacted.",
                    "Cross-site behavior depends on browser defaults instead of an explicit application decision.",
                    "Set SameSite=Lax or Strict unless a documented cross-site flow requires None with Secure.",
                    url,
                )
            )
        if cookie.same_site == "none" and not cookie.secure:
            signals.append(
                _signal(
                    "cookie-samesite-none-secure",
                    f"Cookie {cookie.name} uses SameSite=None without Secure",
                    Severity.MEDIUM,
                    1.0,
                    f"The cookie {cookie.name} declared SameSite=None without Secure; its value was redacted.",
                    "Modern browsers reject this cookie configuration.",
                    "Add Secure when SameSite=None is required, or choose Lax/Strict.",
                    url,
                )
            )

    for header in ("server", "x-powered-by"):
        if header in lowered:
            signals.append(
                _signal(
                    "header-technology-disclosure",
                    "Technology-identifying response header observed",
                    Severity.INFO,
                    0.99,
                    f"The response exposed {header}: {_bounded_header(lowered[header])}.",
                    "Detailed platform identification can reduce an attacker's reconnaissance effort.",
                    "Remove or generalize unnecessary technology-identifying headers.",
                    url,
                )
            )
    return signals


def _signal(
    rule_id: str,
    title: str,
    severity: Severity,
    confidence: float,
    observation: str,
    impact: str,
    recommendation: str,
    url: str,
) -> SecuritySignalV1:
    return SecuritySignalV1(
        rule_id=rule_id,
        title=title,
        severity=severity,
        confidence=confidence,
        observation=observation,
        impact=impact,
        recommendation=recommendation,
        affected_url=url,
    )


def _parse_cookie(raw: str) -> CookieObservationV1:
    parts = [part.strip() for part in raw.split(";")]
    name = parts[0].split("=", 1)[0].strip() or "[unnamed]"
    attributes = {part.lower() for part in parts[1:]}
    same_site: str | None = None
    for attribute in attributes:
        if attribute.startswith("samesite="):
            candidate = attribute.split("=", 1)[1]
            if candidate in {"strict", "lax", "none"}:
                same_site = candidate
    return CookieObservationV1(
        name=_bounded_cookie_name(name),
        secure="secure" in attributes,
        http_only="httponly" in attributes,
        same_site=same_site,
    )


def _has_frame_protection(headers: dict[str, str]) -> bool:
    csp = headers.get("content-security-policy", "").lower()
    return "frame-ancestors" in csp or "x-frame-options" in headers


async def _observe_tls(
    url: str,
    *,
    allow_private_network: bool,
    timeout_seconds: int,
) -> TlsObservationV1 | None:
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        return None
    await ensure_safe_runtime_destination(
        url,
        allow_private_network=allow_private_network,
    )
    host = parts.hostname or ""
    port = parts.port or 443
    context = ssl.create_default_context()
    reader = None
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host,
                port,
                ssl=context,
                server_hostname=host,
            ),
            timeout=timeout_seconds,
        )
        ssl_object = writer.get_extra_info("ssl_object")
        if ssl_object is None:
            return None
        certificate = ssl_object.getpeercert()
        cipher = ssl_object.cipher()
        return TlsObservationV1(
            host=host,
            negotiated_version=ssl_object.version() or "unknown",
            cipher=cipher[0] if cipher else "unknown",
            certificate_subject=_certificate_name(
                certificate.get("subject", ())
            ),
            certificate_issuer=_certificate_name(
                certificate.get("issuer", ())
            ),
            not_before=certificate.get("notBefore"),
            not_after=certificate.get("notAfter"),
        )
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        del reader


def _certificate_name(value) -> str | None:
    pairs = [
        f"{key}={item}"
        for group in value
        for key, item in group
        if key in {"commonName", "organizationName"}
    ]
    return ", ".join(pairs) or None


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))


def _bounded_header(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ")[:1000]


def _bounded_cookie_name(value: str) -> str:
    return "".join(
        character
        for character in value[:100]
        if character.isalnum() or character in {"_", "-", "."}
    ) or "[unnamed]"


def _unique_paths(paths: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            "/" + path.strip("/") if path != "/" else "/"
            for path in paths
        )
    )
