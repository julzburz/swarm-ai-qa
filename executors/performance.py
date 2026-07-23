from __future__ import annotations

import hashlib
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.ports import AgentExecutionContextV1
from schemas.common import (
    EvidenceRefV1,
    MissionMode,
    QualityDomain,
    Severity,
    ToolExecutionStatus,
)
from schemas.evidence import AgentOutputEnvelopeV1, FindingV1, ToolExecutionResultV1
from schemas.execution import SpecialistTaskV1
from schemas.specialists import (
    PerformanceAgentOutputV1,
    PerformanceCoverageV1,
    PerformanceMeasurementV1,
)
from workers.performance import PerformanceWorker, PerformanceWorkerRequestV1

from .models import TestArchitectureOutputV1


METRICS = {
    "time_to_first_byte": ("ttfb_ms", "ms"),
    "dom_content_loaded": ("dom_content_loaded_ms", "ms"),
    "load_event": ("load_event_ms", "ms"),
    "first_contentful_paint": ("first_contentful_paint_ms", "ms"),
    "largest_contentful_paint": ("largest_contentful_paint_ms", "ms"),
    "cumulative_layout_shift": ("cumulative_layout_shift", "score"),
    "transfer_size": ("transfer_bytes", "bytes"),
    "resource_count": ("resource_count", "resources"),
}


class PerformanceExecutor:
    agent_id = "performance_test_engineer"

    def __init__(self, worker: PerformanceWorker) -> None:
        self.worker = worker

    async def execute(
        self,
        task: SpecialistTaskV1,
        context: AgentExecutionContextV1,
    ) -> AgentOutputEnvelopeV1:
        target = context.mission.runtime_target
        if target is None:
            raise ValueError(
                "performance_test_engineer requires a runtime_target"
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
                "performance_test_engineer requires the approved test plan"
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
                "performance plan selected paths outside the runtime allowlist: "
                f"{sorted(unauthorized_paths)}"
            )

        repetitions = {
            MissionMode.QUICK_TASK: 2,
            MissionMode.TARGETED_EXAMINATION: 3,
            MissionMode.FULL_EXAMINATION: 5,
        }[context.mission.mode]
        started_at = datetime.now(timezone.utc)
        started_clock = time.monotonic()
        result = await self.worker.run(
            PerformanceWorkerRequestV1(
                run_id=context.run_id,
                task_id=task.task_id,
                base_url=target.base_url,
                allowed_paths=planned_paths,
                blocked_paths=target.blocked_paths,
                repetitions=repetitions,
                max_requests=min(
                    max(20, task.estimated_requests),
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
        successful = [
            sample
            for sample in result.samples
            if sample.status == "passed"
        ]
        if not successful:
            raise RuntimeError(
                "Performance smoke produced no successful samples"
            )

        measurements: list[PerformanceMeasurementV1] = []
        findings: list[FindingV1] = []
        urls = list(dict.fromkeys(sample.final_url for sample in successful))
        for url in urls:
            page_samples = [
                sample
                for sample in successful
                if sample.final_url == url
            ]
            page_measurements: dict[str, PerformanceMeasurementV1] = {}
            for metric, (field_name, unit) in METRICS.items():
                values = [
                    float(value)
                    for sample in page_samples
                    if (value := getattr(sample, field_name)) is not None
                ]
                if not values:
                    continue
                measurement = PerformanceMeasurementV1(
                    metric=metric,
                    value=_percentile(values, 0.75),
                    unit=unit,
                    sample_count=len(values),
                    median=statistics.median(values),
                    variance=(
                        statistics.pvariance(values)
                        if len(values) > 1
                        else 0.0
                    ),
                    environment_context=(
                        f"url={url}; lab=Playwright Chromium; "
                        f"network={result.network_profile}; "
                        f"viewport={result.viewport}; cold_context=true"
                    ),
                    evidence_refs=[report_ref],
                )
                measurements.append(measurement)
                page_measurements[metric] = measurement
            findings.extend(
                _threshold_findings(
                    context.run_id,
                    task.task_id,
                    url,
                    page_measurements,
                    report_ref,
                )
            )

        coverage = PerformanceCoverageV1(
            pages_measured=len(urls),
            repetitions_requested=repetitions,
            successful_samples=len(successful),
            failed_samples=len(result.samples) - len(successful),
            network_profile=result.network_profile,
            viewport=result.viewport,
        )
        tool_execution = ToolExecutionResultV1(
            task_id=task.task_id,
            capability_id="collect_web_vitals",
            tool_name="Playwright Chromium performance smoke",
            tool_version=(
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
                f"Completed {len(successful)}/{len(result.samples)} isolated "
                f"single-user sample(s) across {len(urls)} route(s) with "
                f"{result.request_count} bounded request(s). No load test was "
                "performed."
            ),
        )
        output = PerformanceAgentOutputV1(
            run_id=context.run_id,
            task_id=task.task_id,
            measurements=measurements,
            findings=findings,
            coverage=coverage,
            baseline_compared=False,
            tool_executions=[tool_execution],
            residual_risks=[
                "Lab samples do not replace 75th-percentile real-user field data.",
                "INP was not measured because no representative user interaction was executed.",
                "No baseline was supplied, so signals are not classified as regressions.",
                "Same-origin resource policy may exclude third-party assets used by the real page.",
            ],
        )
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="PerformanceAgentOutputV1",
            output=output.model_dump(mode="json"),
            evidence_refs=[report_ref],
        )


def _threshold_findings(
    run_id,
    task_id,
    url: str,
    measurements: dict[str, PerformanceMeasurementV1],
    evidence: EvidenceRefV1,
) -> list[FindingV1]:
    findings: list[FindingV1] = []
    configurations = [
        (
            "largest_contentful_paint",
            2500.0,
            4000.0,
            "perf-lcp",
            "Largest Contentful Paint",
            "Loading of the main visible content may feel slow.",
            "Prioritize the LCP resource and reduce render-blocking work.",
        ),
        (
            "cumulative_layout_shift",
            0.1,
            0.25,
            "perf-cls",
            "Cumulative Layout Shift",
            "Unexpected layout movement can disrupt reading and interaction.",
            "Reserve layout space and avoid late content insertion above existing content.",
        ),
        (
            "time_to_first_byte",
            800.0,
            1800.0,
            "perf-ttfb",
            "Time to First Byte",
            "Slow server response can delay every later rendering milestone.",
            "Review server processing, caching, redirects and connection setup.",
        ),
    ]
    for metric, good, poor, rule_id, label, impact, recommendation in configurations:
        measurement = measurements.get(metric)
        if measurement is None or measurement.value <= good:
            continue
        severity = (
            Severity.HIGH
            if measurement.value > poor
            else Severity.MEDIUM
        )
        confidence = 0.85 if measurement.sample_count >= 3 else 0.8
        findings.append(
            FindingV1(
                run_id=run_id,
                task_id=task_id,
                reported_by="performance_test_engineer",
                domain=QualityDomain.PERFORMANCE,
                title=f"Lab performance signal: {label} exceeds the good threshold",
                severity=severity,
                confidence=confidence,
                observation=(
                    f"The lab p75 {label} was {measurement.value:.2f} "
                    f"{measurement.unit} across {measurement.sample_count} "
                    f"cold-context sample(s) on {url}. This is a threshold "
                    "signal, not a regression claim."
                ),
                impact=impact,
                reproduction_steps=[
                    f"Navigate to {url} in an isolated Chromium context",
                    "Collect the same metric across three cold-context samples",
                    "Calculate the lab 75th percentile and compare with the documented threshold",
                ],
                evidence_refs=[evidence],
                recommendation=recommendation,
                affected_locations=[url],
                rule_id=rule_id,
            )
        )
    return findings


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _report_ref(path_value: str, run_id, task_id) -> EvidenceRefV1:
    path = Path(path_value)
    raw = path.read_bytes()
    return EvidenceRefV1(
        uri=(
            f"artifact://performance/{run_id}/{task_id}/smoke/"
            f"{path.name}"
        ),
        media_type="application/json",
        sha256=hashlib.sha256(raw).hexdigest(),
        redacted=True,
        description=(
            "Redacted single-user lab performance samples and context"
        ),
    )


def _path_matches(path: str, allowed: str) -> bool:
    prefix = "/" + allowed.strip("/")
    return prefix == "/" or path == prefix or path.startswith(prefix + "/")
