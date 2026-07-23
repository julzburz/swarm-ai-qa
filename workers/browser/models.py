from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field

from schemas.common import NonEmptyStr, StrictModel


class BrowserWorkerRequestV1(StrictModel):
    run_id: UUID
    task_id: UUID
    base_url: AnyHttpUrl
    allowed_paths: list[NonEmptyStr] = Field(min_length=1)
    blocked_paths: list[NonEmptyStr] = Field(default_factory=list)
    allow_private_network: bool = False
    max_requests: int = Field(gt=0, le=10_000)
    timeout_seconds: int = Field(gt=0, le=86_400)


class BrowserJourneyCaptureV1(StrictModel):
    name: NonEmptyStr
    path: NonEmptyStr
    final_url: NonEmptyStr
    status: Literal["passed", "failed", "blocked"]
    http_status: int | None = Field(default=None, ge=100, le=599)
    title: str = ""
    duration_ms: int = Field(ge=0)
    screenshot_path: NonEmptyStr | None = None
    console_errors: list[str] = Field(default_factory=list)
    page_errors: list[str] = Field(default_factory=list)
    request_failures: list[str] = Field(default_factory=list)


class BrowserWorkerResultV1(StrictModel):
    journeys: list[BrowserJourneyCaptureV1] = Field(min_length=1)
    trace_path: NonEmptyStr
    request_count: int = Field(ge=0)
    blocked_requests: list[str] = Field(default_factory=list)
    playwright_version: NonEmptyStr
    browser_version: NonEmptyStr
