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
    interaction_mode: Literal[
        "navigation_only",
        "safe_staging",
    ] = "navigation_only"
    allow_get_form_submission: bool = False
    max_interactions_per_path: int = Field(ge=0, le=10, default=3)
    viewport_profiles: list[
        Literal["desktop", "tablet", "mobile"]
    ] = Field(default_factory=lambda: ["desktop"], min_length=1)
    max_requests: int = Field(gt=0, le=10_000)
    timeout_seconds: int = Field(gt=0, le=86_400)


class BrowserInteractionStepCaptureV1(StrictModel):
    action: Literal[
        "click_safe_link",
        "fill_safe_field",
        "submit_safe_get_form",
        "assert_safe_destination",
    ]
    status: Literal["passed", "failed", "blocked", "skipped"]
    target: NonEmptyStr
    observation: NonEmptyStr
    final_url: NonEmptyStr
    duration_ms: int = Field(ge=0)


class BrowserJourneyCaptureV1(StrictModel):
    name: NonEmptyStr
    path: NonEmptyStr
    viewport_profile: Literal["desktop", "tablet", "mobile"] = "desktop"
    final_url: NonEmptyStr
    status: Literal["passed", "failed", "blocked"]
    http_status: int | None = Field(default=None, ge=100, le=599)
    title: str = ""
    duration_ms: int = Field(ge=0)
    screenshot_path: NonEmptyStr | None = None
    console_errors: list[str] = Field(default_factory=list)
    page_errors: list[str] = Field(default_factory=list)
    request_failures: list[str] = Field(default_factory=list)
    interaction_steps: list[BrowserInteractionStepCaptureV1] = Field(
        default_factory=list
    )


class BrowserWorkerResultV1(StrictModel):
    journeys: list[BrowserJourneyCaptureV1] = Field(min_length=1)
    trace_path: NonEmptyStr
    request_count: int = Field(ge=0)
    blocked_requests: list[str] = Field(default_factory=list)
    blocked_interactions: list[NonEmptyStr] = Field(default_factory=list)
    interaction_mode: Literal[
        "navigation_only",
        "safe_staging",
    ] = "navigation_only"
    playwright_version: NonEmptyStr
    browser_version: NonEmptyStr
