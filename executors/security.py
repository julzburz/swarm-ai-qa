from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.ports import AgentExecutionContextV1
from schemas.common import EvidenceRefV1, QualityDomain, ToolExecutionStatus
from schemas.evidence import (
    AgentOutputEnvelopeV1,
    FindingV1,
    ToolExecutionResultV1,
    VerificationRequestV1,
)
from schemas.execution import SpecialistTaskV1
from schemas.specialists import SecurityAgentOutputV1, SecurityCoverageV1
from workers.security import SecurityWorker, SecurityWorkerRequestV1

from .models import RepositoryAnalysisOutputV1, TestArchitectureOutputV1


class SecurityExecutor:
    agent_id = "security_test_engineer"

    def __init__(self, worker: SecurityWorker) -> None:
        self.worker = worker

    async def execute(
        self,
        task: SpecialistTaskV1,
        context: AgentExecutionContextV1,
    ) -> AgentOutputEnvelopeV1:
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
                "security_test_engineer requires the approved test plan"
            )
        architecture = TestArchitectureOutputV1.model_validate(
            architecture_envelope.output
        )
        target = context.mission.runtime_target
        if target is None:
            return self._repository_scope_output(task, context)
        planned_paths = (
            architecture.test_plan.critical_journeys
            or list(target.allowed_paths)
        )
        unauthorized_paths = {
            path
            for path in planned_paths
            if not any(
                _path_matches(path, allowed)
                for allowed in target.allowed_paths
            )
        }
        if unauthorized_paths:
            raise ValueError(
                "security plan selected paths outside the runtime allowlist: "
                f"{sorted(unauthorized_paths)}"
            )

        started_at = datetime.now(timezone.utc)
        started_clock = time.monotonic()
        result = await self.worker.run(
            SecurityWorkerRequestV1(
                run_id=context.run_id,
                task_id=task.task_id,
                base_url=target.base_url,
                allowed_paths=planned_paths,
                blocked_paths=target.blocked_paths,
                max_requests=min(
                    max(5, task.estimated_requests),
                    context.mission.budget.max_requests,
                ),
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

        findings: list[FindingV1] = []
        verification_requests: list[VerificationRequestV1] = []
        for page in result.pages:
            for signal in page.signals:
                finding = FindingV1(
                    run_id=context.run_id,
                    task_id=task.task_id,
                    reported_by=self.agent_id,
                    domain=QualityDomain.SECURITY,
                    title=signal.title,
                    severity=signal.severity,
                    confidence=signal.confidence,
                    observation=signal.observation,
                    impact=signal.impact,
                    reproduction_steps=[
                        f"Send a bounded GET request to {signal.affected_url}",
                        "Inspect only the returned status, security headers and redacted cookie attributes",
                        f"Compare the observation with passive rule {signal.rule_id}",
                    ],
                    evidence_refs=[report_ref],
                    recommendation=signal.recommendation,
                    affected_locations=[signal.affected_url],
                    rule_id=signal.rule_id,
                )
                findings.append(finding)
                if signal.rule_id.startswith("cookie-"):
                    verification_requests.append(
                        VerificationRequestV1(
                            finding_id=finding.finding_id,
                            from_agent=self.agent_id,
                            to_agent="browser_automation_engineer",
                            question=(
                                "Confirm whether this cookie participates in "
                                "an authenticated or otherwise sensitive browser flow."
                            ),
                            required_evidence=[
                                "Browser cookie metadata with values redacted",
                                "Observed route and flow context",
                            ],
                            context_refs=[report_ref],
                        )
                    )

        coverage = SecurityCoverageV1(
            mode="runtime_passive",
            routes_audited=len(result.pages),
            responses_observed=len(result.pages),
            cookies_observed=sum(len(page.cookies) for page in result.pages),
            tls_observed=result.tls is not None,
            policy_version=result.policy_version,
        )
        tool_execution = ToolExecutionResultV1(
            task_id=task.task_id,
            capability_id="header_audit",
            tool_name="Swarm passive HTTP security auditor",
            tool_version=(
                f"policy={result.policy_version}; "
                f"httpx={result.httpx_version}"
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
                f"Audited {len(result.pages)} allowlisted route(s) with "
                f"{result.request_count} bounded GET request(s), observed "
                f"{coverage.cookies_observed} cookie(s) and produced "
                f"{len(findings)} passive signal(s). No exploitation, "
                "fuzzing or credential use was performed."
            ),
        )
        output = SecurityAgentOutputV1(
            run_id=context.run_id,
            task_id=task.task_id,
            findings=findings,
            verification_requests=verification_requests,
            coverage=coverage,
            tool_executions=[tool_execution],
            residual_risks=[
                "Passive response inspection cannot establish exploitability.",
                "Authenticated, state-changing and hidden routes were not tested.",
                "No vulnerability exploitation, fuzzing, credential attack, dependency scan or source-code scan was performed.",
            ],
        )
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="SecurityAgentOutputV1",
            output=output.model_dump(mode="json"),
            evidence_refs=[report_ref],
        )

    def _repository_scope_output(
        self,
        task: SpecialistTaskV1,
        context: AgentExecutionContextV1,
    ) -> AgentOutputEnvelopeV1:
        repository_envelope = next(
            (
                output
                for output in context.dependency_outputs.values()
                if output.agent_id == "repository_analyst"
            ),
            None,
        )
        if repository_envelope is None:
            raise ValueError(
                "repository-only security scope requires repository evidence"
            )
        repository = RepositoryAnalysisOutputV1.model_validate(
            repository_envelope.output
        )
        evidence = repository.repository_context.evidence_refs
        now = datetime.now(timezone.utc)
        coverage = SecurityCoverageV1(
            mode="repository_scope_only",
            repository_snapshot_observed=True,
            routes_audited=0,
            responses_observed=0,
            cookies_observed=0,
            tls_observed=False,
            policy_version="repository-scope-v1",
        )
        tool_execution = ToolExecutionResultV1(
            task_id=task.task_id,
            capability_id="safe_configuration_review",
            tool_name="Swarm repository security scope reviewer",
            tool_version="repository-scope-v1",
            status=ToolExecutionStatus.SUCCEEDED,
            exit_code=0,
            started_at=now,
            completed_at=now,
            duration_ms=0,
            artifact_refs=evidence,
            output_summary=(
                "Reviewed the bounded repository snapshot and project profile "
                "to define security scope. No source, dependency or secret "
                "scanner was executed, so no absence-of-vulnerability claim "
                "is made."
            ),
        )
        output = SecurityAgentOutputV1(
            run_id=context.run_id,
            task_id=task.task_id,
            coverage=coverage,
            tool_executions=[tool_execution],
            residual_risks=[
                "Repository-only security execution currently performs scope review, not static source scanning.",
                "Dependency vulnerabilities, leaked secrets and code-level security flaws remain untested.",
            ],
        )
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="SecurityAgentOutputV1",
            output=output.model_dump(mode="json"),
            evidence_refs=evidence,
        )


def _report_ref(path_value: str, run_id, task_id) -> EvidenceRefV1:
    path = Path(path_value)
    raw = path.read_bytes()
    return EvidenceRefV1(
        uri=(
            f"artifact://security/{run_id}/{task_id}/passive/"
            f"{path.name}"
        ),
        media_type="application/json",
        sha256=hashlib.sha256(raw).hexdigest(),
        redacted=True,
        description=(
            "Passive HTTP, TLS, security-header and redacted cookie metadata"
        ),
    )


def _path_matches(path: str, allowed: str) -> bool:
    prefix = "/" + allowed.strip("/")
    return prefix == "/" or path == prefix or path.startswith(prefix + "/")
