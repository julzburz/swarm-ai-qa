from __future__ import annotations

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
