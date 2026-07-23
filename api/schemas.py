from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from executors.models import RepositoryAnalysisOutputV1
from schemas.common import QualityDomain, Severity, StrictModel
from schemas.evidence import CorrelatedFindingV1
from schemas.mission import MissionMode, SwarmExecutionPlanV1, UserMissionRequestV1
from orchestrator.models import RunStatus


class HealthResponseV1(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["swarm-ai-qa-control-plane"] = "swarm-ai-qa-control-plane"
    version: str
    storage: Literal["sqlite", "neon"]
    authentication: Literal["disabled", "bearer"]


class PlanPreviewResponseV1(StrictModel):
    mission: UserMissionRequestV1
    plan: SwarmExecutionPlanV1
    reconnaissance: RepositoryAnalysisOutputV1 | None = None
    planning_basis: Literal[
        "repository_reconnaissance",
        "runtime_inputs",
        "mission_inputs",
    ] = "mission_inputs"
    missing_executors: list[str]
    executable: bool


class CreateRunRequestV1(StrictModel):
    mission: UserMissionRequestV1
    approved: bool = False
    approved_plan_id: UUID | None = None


class RunAcceptedResponseV1(StrictModel):
    run_id: UUID
    mission_id: UUID
    status: Literal["accepted"] = "accepted"
    plan: SwarmExecutionPlanV1
    state_url: str
    events_url: str
    event_stream_url: str


class RunSummaryV1(StrictModel):
    run_id: UUID
    mission_id: UUID
    objective: str
    mode: MissionMode
    source: Literal["repository", "runtime", "combined"]
    status: RunStatus
    agent_count: int
    completed_agents: int
    created_at: datetime
    updated_at: datetime


class FindingListResponseV1(StrictModel):
    run_id: UUID
    run_status: RunStatus
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    domain: QualityDomain | None = None
    severity: Severity | None = None
    items: list[CorrelatedFindingV1]


class ArtifactSummaryV1(StrictModel):
    artifact_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    uri: str
    media_type: str
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    redacted: bool
    description: str | None = None
    produced_by: str
    task_id: UUID
    available: bool
    download_url: str | None = None


class ArtifactListResponseV1(StrictModel):
    run_id: UUID
    run_status: RunStatus
    total: int = Field(ge=0)
    downloadable: int = Field(ge=0)
    items: list[ArtifactSummaryV1]
