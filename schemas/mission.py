from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from .common import (
    BudgetV1,
    Environment,
    MissionMode,
    NonEmptyStr,
    QualityDomain,
    SourceType,
    StrictModel,
    TaskStatus,
)
from .execution import SpecialistTaskV1
from .project import RepositoryTargetV1
from .common import RuntimeTargetV1


class MissionJobV1(StrictModel):
    job_id: UUID = Field(default_factory=uuid4)
    objective: NonEmptyStr
    domains: set[QualityDomain] = Field(min_length=1)
    required: bool = True


class UserMissionRequestV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    mission_id: UUID = Field(default_factory=uuid4)
    objective: NonEmptyStr
    mode: MissionMode
    repository_target: RepositoryTargetV1 | None = None
    runtime_target: RuntimeTargetV1 | None = None
    pull_request_number: int | None = Field(default=None, gt=0)
    selected_domains: set[QualityDomain] = Field(default_factory=set)
    requested_jobs: list[MissionJobV1] = Field(default_factory=list)
    request_release_decision: bool | None = None
    budget: BudgetV1 = Field(default_factory=BudgetV1)

    @model_validator(mode="after")
    def validate_mission_shape(self) -> "UserMissionRequestV1":
        if self.repository_target is None and self.runtime_target is None:
            raise ValueError("A mission requires a repository or runtime target")
        if self.pull_request_number is not None and self.repository_target is None:
            raise ValueError("pull_request_number requires repository_target")
        if self.mode == MissionMode.QUICK_TASK and not 1 <= len(self.requested_jobs) <= 2:
            raise ValueError("quick_task requires one or two requested jobs")
        if self.mode == MissionMode.TARGETED_EXAMINATION and not self.selected_domains:
            raise ValueError("targeted_examination requires selected_domains")
        if self.mode == MissionMode.FULL_EXAMINATION and self.request_release_decision is False:
            raise ValueError("full_examination cannot explicitly disable release decision")
        if self.runtime_target is not None:
            self.runtime_target.assert_safe_defaults()
        return self


class MissionInterpretationV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    mission_id: UUID
    interpreted_objective: NonEmptyStr
    mode: MissionMode
    source_type: SourceType
    jobs: list[MissionJobV1] = Field(min_length=1)
    applicable_domains: set[QualityDomain] = Field(min_length=1)
    excluded_domains: dict[QualityDomain, NonEmptyStr] = Field(default_factory=dict)
    release_decision_required: bool
    assumptions: list[NonEmptyStr] = Field(default_factory=list)
    missing_information: list[NonEmptyStr] = Field(default_factory=list)
    requires_user_confirmation: bool = True

    @model_validator(mode="after")
    def source_and_mode_are_consistent(self) -> "MissionInterpretationV1":
        if self.mode == MissionMode.QUICK_TASK and len(self.jobs) > 2:
            raise ValueError("quick_task interpretation cannot contain more than two jobs")
        return self


class SwarmExecutionPlanV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    summary: NonEmptyStr
    tasks: list[SpecialistTaskV1] = Field(min_length=1)
    selected_agents: set[NonEmptyStr] = Field(min_length=1)
    agent_selection_reasons: dict[NonEmptyStr, NonEmptyStr]
    estimated_duration_seconds: int = Field(gt=0)
    estimated_requests: int = Field(ge=0)
    production_restrictions: list[NonEmptyStr] = Field(default_factory=list)
    requires_approval: bool = True

    @model_validator(mode="after")
    def agents_and_tasks_are_consistent(self) -> "SwarmExecutionPlanV1":
        task_agents = {task.agent_id for task in self.tasks}
        if task_agents - self.selected_agents:
            raise ValueError("Every task agent must appear in selected_agents")
        missing_reasons = self.selected_agents - set(self.agent_selection_reasons)
        if missing_reasons:
            raise ValueError(f"Missing selection reasons for agents: {missing_reasons}")
        return self


class ApprovalRequestV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    approval_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    requested_action: NonEmptyStr
    reason: NonEmptyStr
    environment: Environment
    risk_summary: NonEmptyStr
    expires_at: datetime | None = None


class RunStateUpdateV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    task_id: UUID | None = None
    agent_id: NonEmptyStr
    status: TaskStatus
    message: NonEmptyStr
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EscalationV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    escalation_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    from_agent: NonEmptyStr
    reason: NonEmptyStr
    blocking: bool
    requested_resolution: NonEmptyStr
    evidence_refs: list[str] = Field(default_factory=list)

