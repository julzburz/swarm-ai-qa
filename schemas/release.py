from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from .common import EvidenceRefV1, NonEmptyStr, QualityDomain, Severity, StrictModel
from .evidence import CorrelatedFindingV1, NormalizedEvidenceSetV1
from .execution import CoverageSummaryV1


class PolicyGateV1(StrictModel):
    gate_id: NonEmptyStr
    description: NonEmptyStr
    blocking: bool = True
    domain: QualityDomain | None = None
    maximum_severity: Severity | None = None
    requires_verified_finding: bool = False


class PolicySnapshotV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    policy_id: NonEmptyStr
    version: NonEmptyStr
    gates: list[PolicyGateV1] = Field(default_factory=list)
    minimum_ready_score: float = Field(default=90, ge=0, le=100)
    minimum_conditional_score: float = Field(default=75, ge=0, le=100)
    minimum_manual_review_score: float = Field(default=50, ge=0, le=100)

    @model_validator(mode="after")
    def thresholds_are_descending(self) -> "PolicySnapshotV1":
        if not (
            self.minimum_ready_score
            >= self.minimum_conditional_score
            >= self.minimum_manual_review_score
        ):
            raise ValueError("Release score thresholds must be descending")
        return self


class ReleaseDecisionRequestV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    plan_id: UUID
    policy: PolicySnapshotV1
    evidence: NormalizedEvidenceSetV1
    coverage: CoverageSummaryV1


class GateResultV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    gate_id: NonEmptyStr
    status: Literal["passed", "failed", "not_evaluated"]
    blocking: bool
    explanation: NonEmptyStr
    policy_ref: NonEmptyStr
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def evaluated_gate_requires_evidence(self) -> "GateResultV1":
        if self.status in {"passed", "failed"} and not self.evidence_refs:
            raise ValueError("Evaluated gate requires evidence")
        return self


class ScoreComponentV1(StrictModel):
    domain: QualityDomain
    score: float = Field(ge=0, le=100)
    weight: float = Field(gt=0, le=1)
    explanation: NonEmptyStr
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class ReleaseConfidenceBreakdownV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    components: list[ScoreComponentV1] = Field(min_length=1)
    evidence_completeness: float = Field(ge=0, le=1)
    tool_reliability: float = Field(ge=0, le=1)
    experimental_weights: bool = True
    total_score: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def weights_and_total_are_consistent(self) -> "ReleaseConfidenceBreakdownV1":
        weight_sum = sum(component.weight for component in self.components)
        if abs(weight_sum - 1.0) > 0.001:
            raise ValueError("Score component weights must sum to 1.0")
        calculated = sum(component.score * component.weight for component in self.components)
        if abs(calculated - self.total_score) > 0.1:
            raise ValueError("total_score must equal the weighted component score")
        return self


class ResidualRiskV1(StrictModel):
    risk_id: UUID = Field(default_factory=uuid4)
    description: NonEmptyStr
    reason_unresolved: NonEmptyStr
    severity: Severity
    recommended_action: NonEmptyStr


class RequiredActionV1(StrictModel):
    action_id: UUID = Field(default_factory=uuid4)
    description: NonEmptyStr
    owner_role: NonEmptyStr
    blocking: bool


class ReleaseDecisionV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    decision: Literal["ready", "conditional", "manual_review", "blocked"]
    score: ReleaseConfidenceBreakdownV1
    gate_results: list[GateResultV1]
    residual_risks: list[ResidualRiskV1] = Field(default_factory=list)
    required_actions: list[RequiredActionV1] = Field(default_factory=list)
    summary: NonEmptyStr

    @model_validator(mode="after")
    def decision_respects_blocking_gates(self) -> "ReleaseDecisionV1":
        blocking_failure = any(
            gate.blocking and gate.status == "failed" for gate in self.gate_results
        )
        if blocking_failure and self.decision != "blocked":
            raise ValueError("A blocking gate failure requires decision=blocked")
        if self.decision == "ready" and self.residual_risks:
            critical_or_high = {
                Severity.CRITICAL,
                Severity.HIGH,
            }
            if any(risk.severity in critical_or_high for risk in self.residual_risks):
                raise ValueError("Ready decision cannot contain high or critical residual risk")
        return self

