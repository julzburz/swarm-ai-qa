from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.ports import AgentExecutionContextV1
from schemas.common import EvidenceRefV1, QualityDomain, Severity, ToolExecutionStatus
from schemas.evidence import AgentOutputEnvelopeV1, FindingV1, ToolExecutionResultV1
from schemas.execution import JourneyResultV1, JourneyStepResultV1, RuntimeObservationV1, SpecialistTaskV1
from schemas.specialists import BrowserAgentOutputV1
from workers.browser import BrowserWorker, BrowserWorkerRequestV1

from .models import TestArchitectureOutputV1


class BrowserAutomationExecutor:
    agent_id = "browser_automation_engineer"

    def __init__(self, worker: BrowserWorker) -> None:
        self.worker = worker

    async def execute(
        self,
        task: SpecialistTaskV1,
        context: AgentExecutionContextV1,
    ) -> AgentOutputEnvelopeV1:
        target = context.mission.runtime_target
        if target is None:
            raise ValueError("browser_automation_engineer requires a runtime_target")
        architecture_envelope = next(
            (
                output
                for output in context.dependency_outputs.values()
                if output.agent_id == "test_architect"
            ),
            None,
        )
        if architecture_envelope is None:
            raise ValueError("browser_automation_engineer requires the approved test plan")
        architecture = TestArchitectureOutputV1.model_validate(
            architecture_envelope.output
        )
        planned_paths = architecture.test_plan.critical_journeys
        if not planned_paths:
            raise ValueError("approved test plan contains no browser journeys")
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
                f"test plan selected paths outside the runtime allowlist: "
                f"{sorted(unauthorized_paths)}"
            )
        started_at = datetime.now(timezone.utc)
        started_clock = time.monotonic()
        result = await self.worker.run(
            BrowserWorkerRequestV1(
                run_id=context.run_id,
                task_id=task.task_id,
                base_url=target.base_url,
                allowed_paths=planned_paths,
                blocked_paths=target.blocked_paths,
                max_requests=min(100, context.mission.budget.max_requests),
                timeout_seconds=min(task.timeout_seconds, context.mission.budget.max_duration_seconds),
            )
        )
        completed_at = datetime.now(timezone.utc)
        trace_ref = _artifact_ref(result.trace_path, context.run_id, task.task_id, "trace")
        artifact_refs = [trace_ref]
        journeys: list[JourneyResultV1] = []
        observations: list[RuntimeObservationV1] = []
        findings: list[FindingV1] = []

        for capture in result.journeys:
            evidence = [trace_ref]
            if capture.screenshot_path:
                screenshot = _artifact_ref(
                    capture.screenshot_path,
                    context.run_id,
                    task.task_id,
                    "screenshot",
                )
                evidence.insert(0, screenshot)
                artifact_refs.append(screenshot)
            observation_text = (
                f"Navigation to {capture.final_url} returned HTTP {capture.http_status}; "
                f"console_errors={len(capture.console_errors)}, "
                f"page_errors={len(capture.page_errors)}, "
                f"request_failures={len(capture.request_failures)}."
            )
            journeys.append(
                JourneyResultV1(
                    journey_id=f"browser:{task.task_id}:{capture.path}",
                    task_id=task.task_id,
                    name=capture.name,
                    status=capture.status,
                    steps=[
                        JourneyStepResultV1(
                            step=f"Open {capture.path}",
                            status=capture.status,
                            observation=observation_text,
                            duration_ms=capture.duration_ms,
                            evidence_refs=evidence,
                        )
                    ],
                    environment_url=capture.final_url,
                    evidence_refs=evidence,
                    confidence=0.95 if capture.http_status is not None else 0.7,
                )
            )
            for category, values in (
                ("console", capture.console_errors),
                ("console", capture.page_errors),
                ("network", capture.request_failures),
            ):
                for value in values:
                    observations.append(
                        RuntimeObservationV1(
                            task_id=task.task_id,
                            source=category,
                            observation=value,
                            confidence=0.9,
                            evidence_refs=evidence,
                            sensitive_values_redacted=True,
                        )
                    )
            if capture.status == "failed":
                findings.append(
                    FindingV1(
                        run_id=context.run_id,
                        task_id=task.task_id,
                        reported_by=self.agent_id,
                        domain=QualityDomain.FUNCTIONAL,
                        title=f"Browser journey failed: {capture.name}",
                        severity=Severity.MEDIUM,
                        confidence=0.9,
                        observation=observation_text,
                        impact="The assigned user-facing route did not complete without observable errors.",
                        reproduction_steps=[f"Navigate to {capture.final_url}"],
                        evidence_refs=evidence,
                        recommendation="Review the trace and screenshot, then reproduce in the same environment.",
                        affected_locations=[capture.final_url],
                    )
                )

        if result.blocked_requests:
            observations.append(
                RuntimeObservationV1(
                    task_id=task.task_id,
                    source="network",
                    observation=(
                        f"Browser policy blocked {len(result.blocked_requests)} request(s): "
                        + ", ".join(result.blocked_requests[:10])
                    ),
                    confidence=1.0,
                    evidence_refs=[trace_ref],
                    sensitive_values_redacted=True,
                )
            )

        artifact_refs = _unique_evidence(artifact_refs)
        tool_execution = ToolExecutionResultV1(
            task_id=task.task_id,
            capability_id="navigate_flow",
            tool_name="Playwright Chromium",
            tool_version=f"playwright={result.playwright_version}; chromium={result.browser_version}",
            status=ToolExecutionStatus.SUCCEEDED,
            exit_code=0,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=max(0, round((time.monotonic() - started_clock) * 1000)),
            artifact_refs=artifact_refs,
            output_summary=(
                f"Executed {len(journeys)} journey(s), observed {result.request_count} request(s), "
                f"blocked {len(result.blocked_requests)}."
            ),
        )
        output = BrowserAgentOutputV1(
            run_id=context.run_id,
            task_id=task.task_id,
            journeys=journeys,
            observations=observations,
            findings=findings,
            tool_executions=[tool_execution],
        )
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="BrowserAgentOutputV1",
            output=output.model_dump(mode="json"),
            evidence_refs=artifact_refs,
        )


def _artifact_ref(
    path_value: str,
    run_id,
    task_id,
    kind: str,
) -> EvidenceRefV1:
    path = Path(path_value)
    raw = path.read_bytes()
    media_type = "application/zip" if kind == "trace" else "image/png"
    return EvidenceRefV1(
        uri=f"artifact://browser/{run_id}/{task_id}/{kind}/{path.name}",
        media_type=media_type,
        sha256=hashlib.sha256(raw).hexdigest(),
        description=f"Playwright {kind} evidence",
    )


def _unique_evidence(values: list[EvidenceRefV1]) -> list[EvidenceRefV1]:
    return list({value.uri: value for value in values}.values())


def _path_matches(path: str, allowed: str) -> bool:
    prefix = "/" + allowed.strip("/")
    return prefix == "/" or path == prefix or path.startswith(prefix + "/")
