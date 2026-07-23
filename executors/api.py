from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.ports import AgentExecutionContextV1
from schemas.common import (
    EvidenceRefV1,
    QualityDomain,
    Severity,
    ToolExecutionStatus,
)
from schemas.evidence import (
    AgentOutputEnvelopeV1,
    FindingV1,
    ToolExecutionResultV1,
)
from schemas.execution import SpecialistTaskV1
from schemas.specialists import (
    ApiAgentOutputV1,
    ApiOperationResultV1,
    ContractCoverageV1,
)
from workers.api import ApiWorker, ApiWorkerRequestV1

from .models import TestArchitectureOutputV1


class ApiTestExecutor:
    agent_id = "api_test_engineer"

    def __init__(self, worker: ApiWorker) -> None:
        self.worker = worker

    async def execute(
        self,
        task: SpecialistTaskV1,
        context: AgentExecutionContextV1,
    ) -> AgentOutputEnvelopeV1:
        target = context.mission.runtime_target
        if target is None:
            raise ValueError(
                "api_test_engineer requires a runtime_target"
            )
        architecture_envelope = next(
            (
                output
                for output in context.dependency_outputs.values()
                if output.agent_id == "test_architect"
            ),
            None,
        )
        if architecture_envelope is None:
            raise ValueError(
                "api_test_engineer requires the approved test plan"
            )
        TestArchitectureOutputV1.model_validate(
            architecture_envelope.output
        )

        started_at = datetime.now(timezone.utc)
        started_clock = time.monotonic()
        result = await self.worker.run(
            ApiWorkerRequestV1(
                run_id=context.run_id,
                task_id=task.task_id,
                base_url=target.base_url,
                allowed_paths=target.allowed_paths,
                blocked_paths=target.blocked_paths,
                max_requests=min(
                    20,
                    context.mission.budget.max_requests,
                ),
                max_operations=20,
                timeout_seconds=min(
                    task.timeout_seconds,
                    context.mission.budget.max_duration_seconds,
                ),
            )
        )
        completed_at = datetime.now(timezone.utc)
        report_ref = _report_ref(
            result.report_path,
            context.run_id,
            task.task_id,
        )

        operations = [
            ApiOperationResultV1(
                operation_id=operation.operation_id,
                method=operation.method,
                path=operation.path,
                source=operation.source,
                url=operation.final_url,
                status=operation.status,
                status_code=operation.status_code,
                latency_ms=operation.latency_ms,
                expected_statuses=operation.expected_statuses,
                schema_valid=operation.schema_valid,
                observation=operation.observation,
                evidence_refs=[report_ref],
            )
            for operation in result.operations
        ]
        findings: list[FindingV1] = []
        if (
            result.contract.discovered
            and result.contract.valid is False
        ):
            findings.append(
                FindingV1(
                    run_id=context.run_id,
                    task_id=task.task_id,
                    reported_by=self.agent_id,
                    domain=QualityDomain.API,
                    title="Discovered OpenAPI contract is structurally invalid",
                    severity=Severity.MEDIUM,
                    confidence=0.99,
                    observation="; ".join(
                        result.contract.structural_errors
                    ),
                    impact=(
                        "Consumers and QA tooling cannot reliably derive "
                        "operations or response expectations."
                    ),
                    reproduction_steps=[
                        (
                            "Send a bounded GET request to "
                            f"{result.contract.source_url}"
                        ),
                        "Validate the document as OpenAPI without executing any operation.",
                    ],
                    evidence_refs=[report_ref],
                    recommendation=(
                        "Repair the OpenAPI structure and publish a valid "
                        "versioned contract."
                    ),
                    affected_locations=[
                        result.contract.source_url
                        or str(target.base_url)
                    ],
                    rule_id="openapi-structure",
                )
            )

        for operation in result.operations:
            if operation.status != "failed":
                continue
            reason = (
                "response-schema-mismatch"
                if operation.schema_valid is False
                else "response-status-mismatch"
            )
            findings.append(
                FindingV1(
                    run_id=context.run_id,
                    task_id=task.task_id,
                    reported_by=self.agent_id,
                    domain=QualityDomain.API,
                    title=(
                        (
                            "API contract mismatch: "
                            if result.contract.discovered
                            else "API safe GET smoke failed: "
                        )
                        + f"{operation.method} {operation.path}"
                    ),
                    severity=Severity.MEDIUM,
                    confidence=0.98,
                    observation=operation.observation,
                    impact=(
                        (
                            "API consumers may receive a status or JSON "
                            "shape that differs from the documented contract."
                        )
                        if result.contract.discovered
                        else (
                            "The public read-only endpoint did not return a "
                            "successful response during the bounded smoke."
                        )
                    ),
                    reproduction_steps=[
                        (
                            f"Send an unauthenticated, bounded "
                            f"{operation.method} request to "
                            f"{operation.requested_url}"
                        ),
                        (
                            "Compare only status and response shape with the "
                            "discovered contract."
                            if result.contract.discovered
                            else (
                                "Confirm the endpoint availability without "
                                "sending credentials or mutation requests."
                            )
                        ),
                    ],
                    evidence_refs=[report_ref],
                    recommendation=(
                        (
                            "Align the implementation and OpenAPI response "
                            "definition, then repeat the safe contract check."
                        )
                        if result.contract.discovered
                        else (
                            "Review the public endpoint availability and "
                            "repeat the bounded GET/HEAD smoke."
                        )
                    ),
                    affected_locations=[operation.final_url],
                    rule_id=reason,
                )
            )

        blocked_operations = list(result.blocked_operations)
        blocked_operations.extend(
            operation.operation_id
            for operation in result.operations
            if operation.status == "blocked"
        )
        coverage = ContractCoverageV1(
            contract_discovered=result.contract.discovered,
            contract_valid=result.contract.valid,
            contract_source_url=result.contract.source_url,
            contract_title=result.contract.title,
            contract_version=result.contract.version,
            openapi_version=result.contract.openapi_version,
            total_operations=result.contract.total_operations,
            assigned_operations=len(result.operations),
            executed_operations=sum(
                operation.status != "blocked"
                for operation in result.operations
            ),
            safe_operations=result.contract.safe_operations,
            response_schemas_validated=sum(
                operation.schema_valid is not None
                for operation in result.operations
            ),
            mutating_operations_blocked=(
                result.contract.mutating_operations
            ),
            blocked_operations=sorted(set(blocked_operations)),
        )
        tool_execution = ToolExecutionResultV1(
            task_id=task.task_id,
            capability_id="validate_openapi",
            tool_name="Swarm safe OpenAPI and HTTP validator",
            tool_version=(
                f"policy={result.policy_version}; "
                f"httpx={result.httpx_version}; "
                f"jsonschema={result.jsonschema_version}"
            ),
            status=ToolExecutionStatus.SUCCEEDED,
            exit_code=0,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=max(
                0,
                round((time.monotonic() - started_clock) * 1000),
            ),
            artifact_refs=[report_ref],
            output_summary=(
                f"Discovered contract={result.contract.discovered}; "
                f"executed {coverage.executed_operations} bounded GET/HEAD "
                f"operation(s), blocked "
                f"{len(coverage.blocked_operations)} unsafe or incomplete "
                "operation(s), and performed zero mutating requests."
            ),
        )
        output = ApiAgentOutputV1(
            run_id=context.run_id,
            task_id=task.task_id,
            operations=operations,
            findings=findings,
            coverage=coverage,
            tool_executions=[tool_execution],
            residual_risks=[
                (
                    "Only public, parameterless GET/HEAD operations were "
                    "executed; authenticated and required-parameter behavior "
                    "remains unverified."
                ),
                (
                    "OpenAPI discovery uses only conventional locations "
                    "inside the explicit route allowlist."
                ),
                (
                    "Response artifacts contain contract metadata and "
                    "validation outcomes, never response body values."
                ),
            ],
        )
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="ApiAgentOutputV1",
            output=output.model_dump(mode="json"),
            evidence_refs=[report_ref],
        )


def _report_ref(
    path_value: str,
    run_id,
    task_id,
) -> EvidenceRefV1:
    path = Path(path_value)
    raw = path.read_bytes()
    return EvidenceRefV1(
        uri=(
            f"artifact://api/{run_id}/{task_id}/contract/"
            f"{path.name}"
        ),
        media_type="application/json",
        sha256=hashlib.sha256(raw).hexdigest(),
        redacted=True,
        description=(
            "OpenAPI metadata and safe GET/HEAD validation results without "
            "response body values"
        ),
    )
