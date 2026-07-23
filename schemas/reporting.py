from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field

from .common import EvidenceRefV1, NonEmptyStr, StrictModel
from .evidence import CorrelatedFindingV1
from .execution import CoverageSummaryV1, TestCaseExecutionV1
from .release import ReleaseDecisionV1


class QaRunReportV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    mission_summary: NonEmptyStr
    execution_summary: NonEmptyStr
    verdict: Literal[
        "approved",
        "approved_with_observations",
        "not_recommended",
        "inconclusive",
    ] = "inconclusive"
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    findings: list[CorrelatedFindingV1] = Field(default_factory=list)
    coverage: CoverageSummaryV1
    test_case_results: list[TestCaseExecutionV1] = Field(
        default_factory=list
    )
    release_decision: ReleaseDecisionV1 | None = None
    limitations: list[NonEmptyStr] = Field(default_factory=list)
    residual_risks: list[NonEmptyStr] = Field(default_factory=list)
    artifact_refs: list[EvidenceRefV1] = Field(default_factory=list)


class GitHubAnnotationV1(StrictModel):
    path: NonEmptyStr
    start_line: int = Field(gt=0)
    end_line: int | None = Field(default=None, gt=0)
    level: Literal["notice", "warning", "failure"]
    title: NonEmptyStr
    message: NonEmptyStr


class GitHubCheckSummaryV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    repository_id: NonEmptyStr
    pull_request_number: int = Field(gt=0)
    name: NonEmptyStr = "Swarm AI QA"
    conclusion: Literal["success", "neutral", "failure", "cancelled", "timed_out", "action_required"]
    title: NonEmptyStr
    summary_markdown: NonEmptyStr
    details_url: AnyHttpUrl | None = None
    annotations: list[GitHubAnnotationV1] = Field(default_factory=list, max_length=50)
