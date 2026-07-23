from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from schemas.common import StrictModel
from schemas.execution import TestPlanV1
from schemas.project import ChangeImpactMapV1, ProjectProfileV1, RepositoryContextV1
from schemas.reporting import QaRunReportV1


class RepositoryAnalysisOutputV1(StrictModel):
    repository_context: RepositoryContextV1
    project_profile: ProjectProfileV1
    change_impact: ChangeImpactMapV1 | None = None


class TestArchitectureOutputV1(StrictModel):
    test_plan: TestPlanV1
    source_profile_id: UUID | None = None
    source_change_id: str | None = None


class EvidenceReportingOutputV1(StrictModel):
    report: QaRunReportV1
    source_output_schemas: list[str] = Field(min_length=1)
    professional_report_formats: list[str] = Field(default_factory=list)


class ReleaseRecommendationOutputV1(StrictModel):
    decision: Literal["ready", "conditional", "blocked"]
    score: float = Field(ge=0, le=100)
    summary: str
    source_report_verdict: Literal[
        "approved",
        "approved_with_observations",
        "not_recommended",
        "inconclusive",
    ]
    blocking_reasons: list[str] = Field(default_factory=list)
