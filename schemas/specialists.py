from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field, model_validator

from .common import Confidence, EvidenceRefV1, NonEmptyStr, QualityDomain, StrictModel
from .evidence import FindingV1, ToolExecutionResultV1, VerificationRequestV1, VerificationResponseV1
from .execution import JourneyResultV1, RuntimeObservationV1


class SpecialistTaskBaseV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    task_id: UUID
    objective: NonEmptyStr
    capability_ids: list[NonEmptyStr] = Field(min_length=1)
    timeout_seconds: int = Field(gt=0, le=86_400, default=600)
    evidence_context: list[EvidenceRefV1] = Field(default_factory=list)


class BrowserTaskV1(SpecialistTaskBaseV1):
    base_url: AnyHttpUrl
    allowed_paths: list[NonEmptyStr] = Field(min_length=1)
    blocked_paths: list[NonEmptyStr] = Field(default_factory=list)
    journey_names: list[NonEmptyStr] = Field(min_length=1)
    test_data_refs: list[UUID] = Field(default_factory=list)
    max_requests: int = Field(gt=0, default=100)
    allow_form_submission: bool = False


class BrowserAgentOutputV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    task_id: UUID
    journeys: list[JourneyResultV1]
    observations: list[RuntimeObservationV1] = Field(default_factory=list)
    findings: list[FindingV1] = Field(default_factory=list)
    verification_responses: list[VerificationResponseV1] = Field(default_factory=list)
    interaction_coverage: "BrowserInteractionCoverageV1" = Field(
        default_factory=lambda: BrowserInteractionCoverageV1()
    )
    tool_executions: list[ToolExecutionResultV1] = Field(min_length=1)


class BrowserInteractionCoverageV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["navigation_only", "safe_staging"] = "navigation_only"
    safe_links_clicked: int = Field(ge=0, default=0)
    safe_fields_filled: int = Field(ge=0, default=0)
    safe_get_forms_submitted: int = Field(ge=0, default=0)
    blocked_interactions: int = Field(ge=0, default=0)
    mutating_requests_allowed: Literal[False] = False
    destructive_actions_executed: Literal[False] = False


class SecurityTaskV1(SpecialistTaskBaseV1):
    repository_id: NonEmptyStr | None = None
    runtime_target_id: UUID | None = None
    changed_paths: list[NonEmptyStr] = Field(default_factory=list)
    safe_checks_only: bool = True

    @model_validator(mode="after")
    def require_security_target(self) -> "SecurityTaskV1":
        if self.repository_id is None and self.runtime_target_id is None:
            raise ValueError("Security task requires repository_id or runtime_target_id")
        if not self.safe_checks_only:
            raise ValueError("SecurityTaskV1 permits safe checks only")
        return self


class SecurityAgentOutputV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    task_id: UUID
    findings: list[FindingV1] = Field(default_factory=list)
    verification_requests: list[VerificationRequestV1] = Field(default_factory=list)
    coverage: "SecurityCoverageV1"
    tool_executions: list[ToolExecutionResultV1] = Field(min_length=1)
    residual_risks: list[NonEmptyStr] = Field(default_factory=list)


class SecurityCoverageV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["runtime_passive", "repository_scope_only"]
    repository_snapshot_observed: bool = False
    routes_audited: int = Field(ge=0)
    responses_observed: int = Field(ge=0)
    cookies_observed: int = Field(ge=0)
    tls_observed: bool
    policy_version: NonEmptyStr
    active_exploitation_performed: Literal[False] = False


class AccessibilityTaskV1(SpecialistTaskBaseV1):
    page_urls: list[AnyHttpUrl] = Field(min_length=1)
    journey_ids: list[NonEmptyStr] = Field(default_factory=list)
    require_keyboard_check: bool = False


class AccessibilityCoverageV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    pages_scanned: int = Field(ge=0)
    states_scanned: int = Field(ge=0)
    automated_rules_run: int = Field(ge=0)
    keyboard_checked: bool
    manual_criteria_not_checked: list[NonEmptyStr] = Field(default_factory=list)


class AccessibilityAgentOutputV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    task_id: UUID
    findings: list[FindingV1] = Field(default_factory=list)
    verification_requests: list[VerificationRequestV1] = Field(default_factory=list)
    coverage: AccessibilityCoverageV1
    tool_executions: list[ToolExecutionResultV1] = Field(min_length=1)


class PerformanceTaskV1(SpecialistTaskBaseV1):
    page_urls: list[AnyHttpUrl] = Field(min_length=1)
    mode: Literal["lighthouse", "single_user_smoke", "approved_load"]
    repetitions: int = Field(gt=0, le=20, default=3)
    max_requests: int = Field(gt=0, default=50)
    baseline_id: UUID | None = None


class PerformanceMeasurementV1(StrictModel):
    metric: NonEmptyStr
    value: float
    unit: NonEmptyStr
    sample_count: int = Field(gt=0)
    median: float | None = None
    variance: float | None = Field(default=None, ge=0)
    environment_context: NonEmptyStr
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class PerformanceBaselineV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    baseline_id: UUID
    target_id: UUID
    environment: NonEmptyStr
    tool_name: NonEmptyStr
    tool_version: NonEmptyStr
    measurements: list[PerformanceMeasurementV1] = Field(min_length=1)


class PerformanceAgentOutputV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    task_id: UUID
    measurements: list[PerformanceMeasurementV1] = Field(min_length=1)
    findings: list[FindingV1] = Field(default_factory=list)
    coverage: "PerformanceCoverageV1"
    baseline_compared: bool = False
    tool_executions: list[ToolExecutionResultV1] = Field(min_length=1)
    residual_risks: list[NonEmptyStr] = Field(default_factory=list)


class PerformanceCoverageV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    pages_measured: int = Field(ge=0)
    repetitions_requested: int = Field(gt=0)
    successful_samples: int = Field(ge=0)
    failed_samples: int = Field(ge=0)
    network_profile: NonEmptyStr
    viewport: NonEmptyStr
    inp_measured: Literal[False] = False
    field_data_compared: Literal[False] = False
    active_load_test_performed: Literal[False] = False


class ApiOperationV1(StrictModel):
    operation_id: NonEmptyStr
    method: Literal["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]
    path: NonEmptyStr
    mutating: bool = False


class ApiContractV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    contract_id: UUID
    format: Literal["openapi", "graphql", "observed_http"]
    version: NonEmptyStr | None = None
    operations: list[ApiOperationV1] = Field(min_length=1)
    source_ref: EvidenceRefV1


class ApiTaskV1(SpecialistTaskBaseV1):
    base_url: AnyHttpUrl
    contract_id: UUID | None = None
    operation_ids: list[NonEmptyStr] = Field(min_length=1)
    production_read_only: bool = True


class ApiOperationResultV1(StrictModel):
    operation_id: NonEmptyStr
    status: Literal["passed", "failed", "blocked"]
    status_code: int | None = Field(default=None, ge=100, le=599)
    latency_ms: int | None = Field(default=None, ge=0)
    schema_valid: bool | None = None
    observation: NonEmptyStr
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class ContractCoverageV1(StrictModel):
    total_operations: int = Field(ge=0)
    assigned_operations: int = Field(ge=0)
    executed_operations: int = Field(ge=0)
    blocked_operations: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def operation_counts_are_consistent(self) -> "ContractCoverageV1":
        if not self.executed_operations <= self.assigned_operations <= self.total_operations:
            raise ValueError("API coverage counts must be ordered executed <= assigned <= total")
        return self


class ApiAgentOutputV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    task_id: UUID
    operations: list[ApiOperationResultV1]
    findings: list[FindingV1] = Field(default_factory=list)
    coverage: ContractCoverageV1
    tool_executions: list[ToolExecutionResultV1] = Field(min_length=1)


class ToolHealthSnapshotV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    capability_id: NonEmptyStr
    tool_name: NonEmptyStr
    tool_version: NonEmptyStr
    status: Literal["healthy", "degraded", "unavailable", "unknown"]
    checked_at: NonEmptyStr
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
