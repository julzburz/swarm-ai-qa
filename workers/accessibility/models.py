from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field

from schemas.common import NonEmptyStr, StrictModel


class AccessibilityWorkerRequestV1(StrictModel):
    run_id: UUID
    task_id: UUID
    base_url: AnyHttpUrl
    allowed_paths: list[NonEmptyStr] = Field(min_length=1)
    blocked_paths: list[NonEmptyStr] = Field(default_factory=list)
    allow_private_network: bool = False
    max_requests: int = Field(gt=0, le=10_000)
    timeout_seconds: int = Field(gt=0, le=86_400)
    wcag_tags: list[NonEmptyStr] = Field(
        default_factory=lambda: [
            "wcag2a",
            "wcag2aa",
            "wcag21a",
            "wcag21aa",
            "wcag22aa",
        ]
    )


class AxeViolationNodeV1(StrictModel):
    target: list[NonEmptyStr] = Field(min_length=1)
    failure_summary: NonEmptyStr


class AxeViolationV1(StrictModel):
    rule_id: NonEmptyStr
    impact: Literal["minor", "moderate", "serious", "critical"]
    description: NonEmptyStr
    help: NonEmptyStr
    help_url: AnyHttpUrl
    tags: list[NonEmptyStr] = Field(default_factory=list)
    nodes: list[AxeViolationNodeV1] = Field(min_length=1)


class AccessibilityPageScanV1(StrictModel):
    path: NonEmptyStr
    final_url: NonEmptyStr
    http_status: int | None = Field(default=None, ge=100, le=599)
    title: str = ""
    axe_version: NonEmptyStr
    duration_ms: int = Field(ge=0)
    rules_run: int = Field(ge=0)
    passes: int = Field(ge=0)
    incomplete: int = Field(ge=0)
    inapplicable: int = Field(ge=0)
    violations: list[AxeViolationV1] = Field(default_factory=list)


class AccessibilityWorkerResultV1(StrictModel):
    pages: list[AccessibilityPageScanV1] = Field(min_length=1)
    report_path: NonEmptyStr
    request_count: int = Field(ge=0)
    blocked_requests: list[str] = Field(default_factory=list)
    playwright_version: NonEmptyStr
    browser_version: NonEmptyStr
    axe_version: NonEmptyStr
    wcag_tags: list[NonEmptyStr] = Field(min_length=1)
