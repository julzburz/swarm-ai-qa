from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field

from schemas.common import NonEmptyStr, StrictModel


class PerformanceWorkerRequestV1(StrictModel):
    run_id: UUID
    task_id: UUID
    base_url: AnyHttpUrl
    allowed_paths: list[NonEmptyStr] = Field(min_length=1)
    blocked_paths: list[NonEmptyStr] = Field(default_factory=list)
    allow_private_network: bool = False
    repetitions: int = Field(gt=0, le=20, default=3)
    max_requests: int = Field(gt=0, le=10_000)
    timeout_seconds: int = Field(gt=0, le=86_400)


class PerformanceSampleV1(StrictModel):
    path: NonEmptyStr
    final_url: NonEmptyStr
    repetition: int = Field(gt=0)
    http_status: int | None = Field(default=None, ge=100, le=599)
    status: Literal["passed", "failed", "blocked"]
    ttfb_ms: float | None = Field(default=None, ge=0)
    dom_content_loaded_ms: float | None = Field(default=None, ge=0)
    load_event_ms: float | None = Field(default=None, ge=0)
    first_contentful_paint_ms: float | None = Field(default=None, ge=0)
    largest_contentful_paint_ms: float | None = Field(default=None, ge=0)
    cumulative_layout_shift: float | None = Field(default=None, ge=0)
    transfer_bytes: int | None = Field(default=None, ge=0)
    resource_count: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)
    error: str | None = None


class PerformanceWorkerResultV1(StrictModel):
    samples: list[PerformanceSampleV1] = Field(min_length=1)
    report_path: NonEmptyStr
    request_count: int = Field(ge=0)
    blocked_requests: list[NonEmptyStr] = Field(default_factory=list)
    playwright_version: NonEmptyStr
    browser_version: NonEmptyStr
    network_profile: Literal["native-cold-context"] = "native-cold-context"
    viewport: Literal["1365x768"] = "1365x768"
