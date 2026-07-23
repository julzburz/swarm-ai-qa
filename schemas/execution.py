from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from .common import (
    BudgetV1,
    Confidence,
    EvidenceRefV1,
    NonEmptyStr,
    QualityDomain,
    StrictModel,
    TaskStatus,
)


class CoverageObjectiveV1(StrictModel):
    objective_id: NonEmptyStr
    domain: QualityDomain
    risk_reference: NonEmptyStr
    description: NonEmptyStr
    mandatory: bool = False
    acceptance_criteria: list[NonEmptyStr] = Field(min_length=1)


class AcceptanceCriterionV1(StrictModel):
    criterion_id: NonEmptyStr
    description: NonEmptyStr
    mandatory: bool = True
    evidence_required: list[NonEmptyStr] = Field(min_length=1)
    pass_condition: NonEmptyStr


class SpecialistTaskV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    task_id: UUID = Field(default_factory=uuid4)
    agent_id: NonEmptyStr
    objective: NonEmptyStr
    domain: QualityDomain
    capability_ids: list[NonEmptyStr] = Field(min_length=1)
    risk_refs: list[NonEmptyStr] = Field(min_length=1)
    depends_on: list[UUID] = Field(default_factory=list)
    dependency_policy: Literal["all_successful", "all_terminal"] = (
        "all_successful"
    )
    timeout_seconds: int = Field(gt=0, le=86_400, default=600)
    estimated_requests: int = Field(ge=0, default=0)
    status: TaskStatus = TaskStatus.PENDING

    @model_validator(mode="after")
    def task_cannot_depend_on_itself(self) -> "SpecialistTaskV1":
        if self.task_id in self.depends_on:
            raise ValueError("A task cannot depend on itself")
        return self


class AgentTaskV1(SpecialistTaskV1):
    """Nombre utilizado por QA Director para una tarea ya asignada."""


class TestDataReferenceV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    data_id: UUID = Field(default_factory=uuid4)
    purpose: NonEmptyStr
    secret_ref: NonEmptyStr | None = None
    fixture_ref: EvidenceRefV1 | None = None
    synthetic: bool = True
    contains_personal_data: bool = False

    @model_validator(mode="after")
    def require_safe_data_reference(self) -> "TestDataReferenceV1":
        if self.secret_ref is None and self.fixture_ref is None:
            raise ValueError("Test data requires a secret_ref or fixture_ref")
        return self


class TestCaseDesignV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: NonEmptyStr
    title: NonEmptyStr
    domain: QualityDomain
    test_type: Literal[
        "smoke",
        "functional",
        "negative",
        "repository",
        "accessibility",
        "security",
        "performance",
        "api",
        "uat",
    ]
    priority: Literal["critical", "high", "medium", "low"]
    risk_reference: NonEmptyStr
    preconditions: list[NonEmptyStr] = Field(min_length=1)
    steps: list[NonEmptyStr] = Field(min_length=1)
    expected_result: NonEmptyStr
    gherkin: NonEmptyStr
    execution_mode: Literal["automated", "manual"]
    assigned_agent: NonEmptyStr
    target_reference: NonEmptyStr | None = None


class TestCaseExecutionV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: NonEmptyStr
    status: Literal[
        "passed",
        "failed",
        "blocked",
        "observed",
        "manual_required",
        "not_executed",
    ]
    observation: NonEmptyStr
    executed_by: NonEmptyStr | None = None
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    finding_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def execution_status_is_truthful(self) -> "TestCaseExecutionV1":
        if self.status == "manual_required" and (
            self.executed_by is not None
            or self.evidence_refs
            or self.finding_ids
        ):
            raise ValueError(
                "A manual-required case cannot claim execution, evidence or findings"
            )
        if self.status in {"passed", "failed", "observed"}:
            if self.executed_by is None or not self.evidence_refs:
                raise ValueError(
                    "Completed cases require an executor and evidence"
                )
        return self


class TestPlanV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    strategy_summary: NonEmptyStr
    coverage_objectives: list[CoverageObjectiveV1] = Field(min_length=1)
    tasks: list[SpecialistTaskV1] = Field(min_length=1)
    test_cases: list[TestCaseDesignV1] = Field(default_factory=list)
    critical_journeys: list[NonEmptyStr] = Field(default_factory=list)
    budget: BudgetV1
    residual_risks: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_task_graph_and_budget(self) -> "TestPlanV1":
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task_id values must be unique")
        known = set(task_ids)
        for task in self.tasks:
            unknown = set(task.depends_on) - known
            if unknown:
                raise ValueError(f"Task {task.task_id} has unknown dependencies: {unknown}")
        if sum(task.estimated_requests for task in self.tasks) > self.budget.max_requests:
            raise ValueError("Planned requests exceed the mission budget")
        case_ids = [test_case.case_id for test_case in self.test_cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id values must be unique")
        return self


class JourneyStepResultV1(StrictModel):
    step: NonEmptyStr
    status: Literal["passed", "failed", "blocked", "skipped"]
    observation: NonEmptyStr
    duration_ms: int = Field(ge=0)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)


class JourneyResultV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    journey_id: NonEmptyStr
    task_id: UUID
    name: NonEmptyStr
    status: Literal["passed", "failed", "blocked"]
    steps: list[JourneyStepResultV1] = Field(min_length=1)
    environment_url: NonEmptyStr
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    confidence: Confidence

    @model_validator(mode="after")
    def journey_status_matches_steps(self) -> "JourneyResultV1":
        statuses = {step.status for step in self.steps}
        if self.status == "passed" and "failed" in statuses:
            raise ValueError("A passed journey cannot contain a failed step")
        if self.status == "failed" and "failed" not in statuses:
            raise ValueError("A failed journey requires a failed step")
        return self


class RuntimeObservationV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    observation_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    source: Literal["browser", "network", "console", "dom", "accessibility_tree", "http"]
    observation: NonEmptyStr
    confidence: Confidence
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    sensitive_values_redacted: bool = True


class CoverageSummaryV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_id: UUID
    total_objectives: int = Field(ge=0)
    completed_objectives: int = Field(ge=0)
    mandatory_objectives_missed: list[NonEmptyStr] = Field(default_factory=list)
    executed_domains: set[QualityDomain] = Field(default_factory=set)
    unexecuted_domains: dict[QualityDomain, NonEmptyStr] = Field(default_factory=dict)
    evidence_completeness: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def completed_cannot_exceed_total(self) -> "CoverageSummaryV1":
        if self.completed_objectives > self.total_objectives:
            raise ValueError("completed_objectives cannot exceed total_objectives")
        return self
