from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.ports import AgentExecutionContextV1
from schemas.common import EvidenceRefV1, QualityDomain, Severity, ToolExecutionStatus
from schemas.evidence import (
    AgentOutputEnvelopeV1,
    FindingV1,
    ToolExecutionResultV1,
    VerificationRequestV1,
)
from schemas.execution import SpecialistTaskV1
from schemas.specialists import AccessibilityAgentOutputV1, AccessibilityCoverageV1
from workers.accessibility import AccessibilityWorker, AccessibilityWorkerRequestV1

from .models import TestArchitectureOutputV1


AXE_SEVERITY = {
    "minor": Severity.LOW,
    "moderate": Severity.MEDIUM,
    "serious": Severity.HIGH,
    "critical": Severity.CRITICAL,
}

USER_IMPACT = {
    "minor": "Some users may encounter unnecessary friction or ambiguity.",
    "moderate": "Users of assistive technology may have difficulty completing the affected task.",
    "serious": "The issue can prevent some users from understanding or operating the affected control.",
    "critical": "The issue can block an essential task for users who rely on assistive technology.",
}


class AccessibilityExecutor:
    agent_id = "accessibility_specialist"

    def __init__(self, worker: AccessibilityWorker) -> None:
        self.worker = worker

    async def execute(
        self,
        task: SpecialistTaskV1,
        context: AgentExecutionContextV1,
    ) -> AgentOutputEnvelopeV1:
        target = context.mission.runtime_target
        if target is None:
            raise ValueError("accessibility_specialist requires a runtime_target")
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
                "accessibility_specialist requires the approved test plan"
            )
        architecture = TestArchitectureOutputV1.model_validate(
            architecture_envelope.output
        )
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
                "accessibility plan selected paths outside the runtime allowlist: "
                f"{sorted(unauthorized_paths)}"
            )

        started_at = datetime.now(timezone.utc)
        started_clock = time.monotonic()
        result = await self.worker.run(
            AccessibilityWorkerRequestV1(
                run_id=context.run_id,
                task_id=task.task_id,
                base_url=target.base_url,
                allowed_paths=planned_paths,
                blocked_paths=target.blocked_paths,
                max_requests=min(100, context.mission.budget.max_requests),
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
            for violation in page.violations:
                targets = [
                    selector
                    for node in violation.nodes
                    for selector in node.target
                ]
                failure_examples = [
                    node.failure_summary
                    for node in violation.nodes[:3]
                ]
                finding = FindingV1(
                    run_id=context.run_id,
                    task_id=task.task_id,
                    reported_by=self.agent_id,
                    domain=QualityDomain.ACCESSIBILITY,
                    title=f"axe {violation.rule_id}: {violation.help}",
                    severity=AXE_SEVERITY[violation.impact],
                    confidence=0.95,
                    observation=(
                        f"axe-core detected {len(violation.nodes)} failing "
                        f"element(s) on {page.final_url}. "
                        + " ".join(failure_examples)
                    ),
                    impact=USER_IMPACT[violation.impact],
                    reproduction_steps=[
                        f"Navigate to {page.final_url}",
                        f"Run axe-core {result.axe_version} with tags "
                        f"{', '.join(result.wcag_tags)}",
                        f"Inspect rule {violation.rule_id} and the reported selectors",
                    ],
                    evidence_refs=[report_ref],
                    recommendation=(
                        f"{violation.help}. Review Deque guidance at "
                        f"{violation.help_url}"
                    ),
                    affected_locations=[
                        page.final_url,
                        *list(dict.fromkeys(targets))[:10],
                    ],
                    rule_id=violation.rule_id,
                )
                findings.append(finding)
                if finding.severity in {Severity.HIGH, Severity.CRITICAL}:
                    verification_requests.append(
                        VerificationRequestV1(
                            finding_id=finding.finding_id,
                            from_agent=self.agent_id,
                            to_agent="browser_automation_engineer",
                            question=(
                                "Verify keyboard navigation and visible focus around "
                                f"axe rule {violation.rule_id} on {page.final_url}."
                            ),
                            required_evidence=[
                                "Keyboard-only traversal observation",
                                "Visible focus order observation",
                            ],
                            context_refs=[report_ref],
                        )
                    )

        coverage = AccessibilityCoverageV1(
            pages_scanned=len(result.pages),
            states_scanned=len(result.pages),
            automated_rules_run=sum(page.rules_run for page in result.pages),
            keyboard_checked=False,
            manual_criteria_not_checked=[
                "Keyboard-only navigation and focus order",
                "Screen-reader announcements and reading order",
                "Zoom, reflow and text-spacing behavior",
                "Hidden, authenticated and interaction-dependent states",
            ],
        )
        tool_execution = ToolExecutionResultV1(
            task_id=task.task_id,
            capability_id="run_axe_audit",
            tool_name="axe-core with Playwright Chromium",
            tool_version=(
                f"axe-core={result.axe_version}; "
                f"playwright={result.playwright_version}; "
                f"chromium={result.browser_version}"
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
                f"Scanned {len(result.pages)} page(s), executed "
                f"{coverage.automated_rules_run} rule-page checks and found "
                f"{len(findings)} violation group(s). Automated results do not "
                "establish full WCAG conformance."
            ),
        )
        output = AccessibilityAgentOutputV1(
            run_id=context.run_id,
            task_id=task.task_id,
            findings=findings,
            verification_requests=verification_requests,
            coverage=coverage,
            tool_executions=[tool_execution],
        )
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="AccessibilityAgentOutputV1",
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
            f"artifact://accessibility/{run_id}/{task_id}/axe/"
            f"{path.name}"
        ),
        media_type="application/json",
        sha256=hashlib.sha256(raw).hexdigest(),
        redacted=True,
        description="Redacted axe-core WCAG A/AA results",
    )


def _path_matches(path: str, allowed: str) -> bool:
    prefix = "/" + allowed.strip("/")
    return prefix == "/" or path == prefix or path.startswith(prefix + "/")
