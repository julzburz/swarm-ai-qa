from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from .common import (
    Confidence,
    EvidenceRefV1,
    NonEmptyStr,
    QualityDomain,
    Severity,
    StrictModel,
    ToolExecutionStatus,
)


class ToolExecutionResultV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    execution_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    capability_id: NonEmptyStr
    tool_name: NonEmptyStr
    tool_version: NonEmptyStr
    status: ToolExecutionStatus
    exit_code: int | None = None
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    artifact_refs: list[EvidenceRefV1] = Field(default_factory=list)
    error_class: NonEmptyStr | None = None
    error_message: NonEmptyStr | None = None
    output_summary: NonEmptyStr | None = None

    @model_validator(mode="after")
    def status_and_error_are_consistent(self) -> "ToolExecutionResultV1":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be before started_at")
        if self.status == ToolExecutionStatus.SUCCEEDED and self.error_class is not None:
            raise ValueError("Successful tool execution cannot have error_class")
        if self.status != ToolExecutionStatus.SUCCEEDED and self.error_class is None:
            raise ValueError("Non-successful tool execution requires error_class")
        return self


class FindingV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    finding_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    task_id: UUID
    reported_by: NonEmptyStr
    domain: QualityDomain
    title: NonEmptyStr
    severity: Severity
    confidence: Confidence
    observation: NonEmptyStr
    inference: NonEmptyStr | None = None
    impact: NonEmptyStr
    reproduction_steps: list[NonEmptyStr] = Field(min_length=1)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    recommendation: NonEmptyStr
    affected_locations: list[NonEmptyStr] = Field(default_factory=list)
    rule_id: NonEmptyStr | None = None
    verified_by: list[NonEmptyStr] = Field(default_factory=list)
    verification_status: Literal["unverified", "confirmed", "rejected", "inconclusive"] = "unverified"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def enforce_severity_confidence(self) -> "FindingV1":
        minimums = {Severity.HIGH: 0.80, Severity.CRITICAL: 0.90}
        required = minimums.get(self.severity)
        if required is not None and self.confidence < required:
            raise ValueError(f"{self.severity.value} finding requires confidence >= {required:.2f}")
        if self.verification_status == "confirmed" and not self.verified_by:
            raise ValueError("Confirmed finding requires at least one verifier")
        if self.reported_by in self.verified_by:
            raise ValueError("A finding cannot be cross-verified by its reporting agent")
        return self


class VerificationRequestV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    from_agent: NonEmptyStr
    to_agent: NonEmptyStr
    question: NonEmptyStr
    required_evidence: list[NonEmptyStr] = Field(min_length=1)
    context_refs: list[EvidenceRefV1] = Field(min_length=1)
    deadline_seconds: int = Field(gt=0, le=3600, default=300)

    @model_validator(mode="after")
    def agents_must_differ(self) -> "VerificationRequestV1":
        if self.from_agent == self.to_agent:
            raise ValueError("Verification must be directed to another agent")
        return self


class VerificationResponseV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    finding_id: UUID
    responder_agent: NonEmptyStr
    status: Literal["confirmed", "rejected", "inconclusive", "blocked"]
    observation: NonEmptyStr
    confidence: Confidence
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    blocker: NonEmptyStr | None = None

    @model_validator(mode="after")
    def evidence_or_blocker_required(self) -> "VerificationResponseV1":
        if self.status in {"confirmed", "rejected"} and not self.evidence_refs:
            raise ValueError("Confirmed or rejected verification requires evidence")
        if self.status == "blocked" and not self.blocker:
            raise ValueError("Blocked verification requires blocker")
        return self


class CorrelatedFindingV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    correlation_id: UUID = Field(default_factory=uuid4)
    primary_finding: FindingV1
    related_finding_ids: list[UUID] = Field(default_factory=list)
    verification_responses: list[VerificationResponseV1] = Field(default_factory=list)
    final_confidence: Confidence
    correlation_reason: NonEmptyStr
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @model_validator(mode="after")
    def confidence_change_requires_verification(self) -> "CorrelatedFindingV1":
        if self.final_confidence != self.primary_finding.confidence and not self.verification_responses:
            raise ValueError("Confidence can change only with verification evidence")
        return self


class ArtifactManifestEntryV1(StrictModel):
    artifact: EvidenceRefV1
    produced_by: NonEmptyStr
    task_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    contains_sensitive_data: bool = False


class ArtifactManifestV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    artifacts: list[ArtifactManifestEntryV1] = Field(default_factory=list)


class AgentOutputEnvelopeV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    task_id: UUID
    agent_id: NonEmptyStr
    output_schema: NonEmptyStr
    output: dict[str, Any]
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NormalizedEvidenceSetV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    tool_executions: list[ToolExecutionResultV1] = Field(default_factory=list)
    findings: list[FindingV1] = Field(default_factory=list)
    correlated_findings: list[CorrelatedFindingV1] = Field(default_factory=list)
    artifact_manifest: ArtifactManifestV1
    invalid_output_count: int = Field(ge=0, default=0)
    conflicts: list[NonEmptyStr] = Field(default_factory=list)

