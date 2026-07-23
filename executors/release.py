from __future__ import annotations

from orchestrator.ports import AgentExecutionContextV1
from schemas.evidence import AgentOutputEnvelopeV1
from schemas.execution import SpecialistTaskV1

from .models import (
    EvidenceReportingOutputV1,
    ReleaseRecommendationOutputV1,
)


class ReleaseManagerExecutor:
    agent_id = "release_manager"

    async def execute(
        self,
        task: SpecialistTaskV1,
        context: AgentExecutionContextV1,
    ) -> AgentOutputEnvelopeV1:
        report_envelope = next(
            (
                output
                for output in context.dependency_outputs.values()
                if output.agent_id == "evidence_reporting_analyst"
            ),
            None,
        )
        if report_envelope is None:
            raise ValueError("release_manager requires the professional QA report")
        reporting = EvidenceReportingOutputV1.model_validate(
            report_envelope.output
        )
        report = reporting.report
        blocking_reasons = [
            *report.limitations,
            *report.coverage.mandatory_objectives_missed,
        ]
        if report.verdict in {"not_recommended", "inconclusive"}:
            decision = "blocked"
            score = max(
                0.0,
                round(report.coverage.evidence_completeness * 60, 1),
            )
        elif report.verdict == "approved_with_observations":
            decision = "conditional"
            score = max(
                60.0,
                round(report.coverage.evidence_completeness * 85, 1),
            )
        else:
            decision = "ready"
            score = max(
                90.0,
                round(report.coverage.evidence_completeness * 100, 1),
            )
        output = ReleaseRecommendationOutputV1(
            decision=decision,
            score=score,
            summary=(
                f"Recomendación {decision}: veredicto del informe "
                f"{report.verdict}, {len(report.findings)} hallazgo(s) y "
                f"{len(report.limitations)} limitación(es)."
            ),
            source_report_verdict=report.verdict,
            blocking_reasons=blocking_reasons,
        )
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="ReleaseRecommendationOutputV1",
            output=output.model_dump(mode="json"),
            evidence_refs=report_envelope.evidence_refs,
        )
