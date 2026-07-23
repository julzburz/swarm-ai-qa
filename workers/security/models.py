from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field

from schemas.common import NonEmptyStr, Severity, StrictModel


class SecurityWorkerRequestV1(StrictModel):
    run_id: UUID
    task_id: UUID
    base_url: AnyHttpUrl
    allowed_paths: list[NonEmptyStr] = Field(min_length=1)
    blocked_paths: list[NonEmptyStr] = Field(default_factory=list)
    allow_private_network: bool = False
    max_requests: int = Field(gt=0, le=10_000)
    timeout_seconds: int = Field(gt=0, le=86_400)


class SecuritySignalV1(StrictModel):
    rule_id: NonEmptyStr
    title: NonEmptyStr
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    observation: NonEmptyStr
    impact: NonEmptyStr
    recommendation: NonEmptyStr
    affected_url: NonEmptyStr


class CookieObservationV1(StrictModel):
    name: NonEmptyStr
    secure: bool
    http_only: bool
    same_site: Literal["strict", "lax", "none"] | None = None
    value_redacted: Literal[True] = True


class TlsObservationV1(StrictModel):
    host: NonEmptyStr
    negotiated_version: NonEmptyStr
    cipher: NonEmptyStr
    certificate_subject: NonEmptyStr | None = None
    certificate_issuer: NonEmptyStr | None = None
    not_before: NonEmptyStr | None = None
    not_after: NonEmptyStr | None = None


class SecurityPageAuditV1(StrictModel):
    path: NonEmptyStr
    requested_url: NonEmptyStr
    final_url: NonEmptyStr
    http_status: int | None = Field(default=None, ge=100, le=599)
    content_type: str = ""
    audited_headers: dict[str, str] = Field(default_factory=dict)
    cookies: list[CookieObservationV1] = Field(default_factory=list)
    signals: list[SecuritySignalV1] = Field(default_factory=list)
    redirects: list[NonEmptyStr] = Field(default_factory=list)
    duration_ms: int = Field(ge=0)


class SecurityWorkerResultV1(StrictModel):
    pages: list[SecurityPageAuditV1] = Field(min_length=1)
    tls: TlsObservationV1 | None = None
    report_path: NonEmptyStr
    request_count: int = Field(ge=0)
    httpx_version: NonEmptyStr
    policy_version: Literal["passive-web-v1"] = "passive-web-v1"
