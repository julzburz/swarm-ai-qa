from __future__ import annotations

from orchestrator.ports import AgentExecutionContextV1
from schemas.common import QualityDomain
from schemas.evidence import AgentOutputEnvelopeV1, CorrelatedFindingV1
from schemas.execution import CoverageSummaryV1, SpecialistTaskV1
from schemas.reporting import QaRunReportV1
from schemas.specialists import BrowserAgentOutputV1

from .models import (
    EvidenceReportingOutputV1,
    RepositoryAnalysisOutputV1,
    TestArchitectureOutputV1,
)


class EvidenceReportingExecutor:
    agent_id = "evidence_reporting_analyst"

    async def execute(self, task: SpecialistTaskV1, context: AgentExecutionContextV1) -> AgentOutputEnvelopeV1:
        outputs = {
            output.agent_id: output for output in context.dependency_outputs.values()
        }
        architecture_envelope = outputs.get("test_architect")
        repository_envelope = outputs.get("repository_analyst")
        browser_envelope = outputs.get("browser_automation_engineer")
        if architecture_envelope is None:
            raise ValueError("reporting requires the approved test architecture")

        architecture = TestArchitectureOutputV1.model_validate(
            architecture_envelope.output
        )
        repository = (
            RepositoryAnalysisOutputV1.model_validate(repository_envelope.output)
            if repository_envelope is not None
            else None
        )
        browser = (
            BrowserAgentOutputV1.model_validate(browser_envelope.output)
            if browser_envelope is not None
            else None
        )
        plan = architecture.test_plan
        artifact_refs = _unique_evidence(
            [
                evidence
                for envelope in context.dependency_outputs.values()
                for evidence in envelope.evidence_refs
            ]
        )

        executed_domains: set[QualityDomain] = set()
        if repository is not None:
            executed_domains.add(QualityDomain.REPOSITORY)
        if browser is not None:
            executed_domains.add(QualityDomain.FUNCTIONAL)
        completed_objectives = [
            objective
            for objective in plan.coverage_objectives
            if objective.domain in executed_domains
        ]
        missed_objectives = [
            objective.description
            for objective in plan.coverage_objectives
            if objective.mandatory and objective.domain not in executed_domains
        ]
        coverage = CoverageSummaryV1(
            plan_id=plan.plan_id,
            total_objectives=len(plan.coverage_objectives),
            completed_objectives=len(completed_objectives),
            mandatory_objectives_missed=missed_objectives,
            executed_domains=executed_domains,
            evidence_completeness=1.0 if artifact_refs else 0.0,
        )

        repository_evidence = []
        correlation_context = ""
        if repository is not None:
            if repository.change_impact is not None:
                repository_evidence = repository.change_impact.evidence_refs
                correlation_context = (
                    f"bounded change context {repository.change_impact.change_id}"
                )
            else:
                repository_evidence = repository.project_profile.evidence_refs
                correlation_context = (
                    f"repository profile {repository.project_profile.profile_id}"
                )

        correlated: list[CorrelatedFindingV1] = []
        if browser is not None:
            for finding in browser.findings:
                evidence = _unique_evidence(
                    [*finding.evidence_refs, *repository_evidence]
                )
                reason = (
                    "Browser finding preserved and correlated with "
                    f"{correlation_context}; no source-code causality is asserted."
                    if correlation_context
                    else "Single browser finding preserved without unsupported deduplication."
                )
                correlated.append(
                    CorrelatedFindingV1(
                        primary_finding=finding,
                        final_confidence=finding.confidence,
                        correlation_reason=reason,
                        evidence_refs=evidence,
                    )
                )

        residual_risks = list(plan.residual_risks)
        summary_parts: list[str] = []
        if repository is not None:
            summary_parts.append(
                "Repository inspection and evidence-backed planning completed"
            )
        if browser is not None:
            passed = sum(journey.status == "passed" for journey in browser.journeys)
            summary_parts.append(
                f"Playwright executed {len(browser.journeys)} architect-selected "
                f"journey(s); {passed} passed and "
                f"{len(browser.journeys) - passed} did not pass"
            )
            residual_risks.append(
                "Browser coverage is limited to explicitly allowlisted, "
                "navigation-only journeys."
            )
        if repository is not None and browser is not None:
            residual_risks.append(
                "Repository and runtime evidence are correlated by mission and "
                "risk context; route-to-source causality remains unproven."
            )
        execution_summary = (
            "; ".join(summary_parts)
            + ". No repository commands were executed and no source files were modified."
        )
        source_schemas = [
            envelope.output_schema
            for envelope in context.dependency_outputs.values()
        ]

        report = QaRunReportV1(
            run_id=context.run_id,
            mission_summary=context.mission.objective,
            execution_summary=execution_summary,
            findings=correlated,
            coverage=coverage,
            residual_risks=residual_risks,
            artifact_refs=artifact_refs,
        )
        output = EvidenceReportingOutputV1(
            report=report,
            source_output_schemas=source_schemas,
        )
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="EvidenceReportingOutputV1",
            output=output.model_dump(mode="json"),
            evidence_refs=artifact_refs,
        )


def _unique_evidence(values):
    return list({value.uri: value for value in values}.values())
