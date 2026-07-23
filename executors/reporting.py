from __future__ import annotations

from orchestrator.ports import AgentExecutionContextV1
from schemas.common import QualityDomain
from schemas.evidence import AgentOutputEnvelopeV1, CorrelatedFindingV1
from schemas.execution import CoverageSummaryV1, SpecialistTaskV1
from schemas.reporting import QaRunReportV1
from schemas.specialists import (
    AccessibilityAgentOutputV1,
    BrowserAgentOutputV1,
    SecurityAgentOutputV1,
)

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
        accessibility_envelope = outputs.get("accessibility_specialist")
        security_envelope = outputs.get("security_test_engineer")
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
        accessibility = (
            AccessibilityAgentOutputV1.model_validate(
                accessibility_envelope.output
            )
            if accessibility_envelope is not None
            else None
        )
        security = (
            SecurityAgentOutputV1.model_validate(security_envelope.output)
            if security_envelope is not None
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
        if accessibility is not None:
            executed_domains.add(QualityDomain.ACCESSIBILITY)
        if security is not None:
            executed_domains.add(QualityDomain.SECURITY)
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
                related_accessibility = (
                    [
                        candidate
                        for candidate in accessibility.findings
                        if set(candidate.affected_locations)
                        & set(finding.affected_locations)
                    ]
                    if accessibility is not None
                    else []
                )
                evidence = _unique_evidence(
                    [
                        *finding.evidence_refs,
                        *repository_evidence,
                        *[
                            evidence
                            for candidate in related_accessibility
                            for evidence in candidate.evidence_refs
                        ],
                    ]
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
                        related_finding_ids=[
                            candidate.finding_id
                            for candidate in related_accessibility
                        ],
                        final_confidence=finding.confidence,
                        correlation_reason=reason,
                        evidence_refs=evidence,
                    )
                )
        if accessibility is not None:
            for finding in accessibility.findings:
                matching_journeys = (
                    [
                        journey
                        for journey in browser.journeys
                        if journey.environment_url
                        in finding.affected_locations
                    ]
                    if browser is not None
                    else []
                )
                matching_browser_findings = (
                    [
                        candidate
                        for candidate in browser.findings
                        if set(candidate.affected_locations)
                        & set(finding.affected_locations)
                    ]
                    if browser is not None
                    else []
                )
                evidence = _unique_evidence(
                    [
                        *finding.evidence_refs,
                        *repository_evidence,
                        *[
                            evidence
                            for journey in matching_journeys
                            for evidence in journey.evidence_refs
                        ],
                        *[
                            evidence
                            for candidate in matching_browser_findings
                            for evidence in candidate.evidence_refs
                        ],
                    ]
                )
                if matching_journeys:
                    reason = (
                        "Automated axe finding correlated with Playwright "
                        "navigation evidence for the same URL. Keyboard and "
                        "screen-reader behavior remain manually unverified."
                    )
                elif correlation_context:
                    reason = (
                        "Automated axe finding correlated with "
                        f"{correlation_context}; no source-code causality or "
                        "full WCAG conformance is asserted."
                    )
                else:
                    reason = (
                        "Automated axe finding preserved without claiming "
                        "manual accessibility verification."
                    )
                correlated.append(
                    CorrelatedFindingV1(
                        primary_finding=finding,
                        related_finding_ids=[
                            candidate.finding_id
                            for candidate in matching_browser_findings
                        ],
                        final_confidence=finding.confidence,
                        correlation_reason=reason,
                        evidence_refs=evidence,
                    )
                )
        if security is not None:
            for finding in security.findings:
                matching_journeys = (
                    [
                        journey
                        for journey in browser.journeys
                        if journey.environment_url
                        in finding.affected_locations
                    ]
                    if browser is not None
                    else []
                )
                evidence = _unique_evidence(
                    [
                        *finding.evidence_refs,
                        *repository_evidence,
                        *[
                            evidence
                            for journey in matching_journeys
                            for evidence in journey.evidence_refs
                        ],
                    ]
                )
                if matching_journeys:
                    reason = (
                        "Passive security signal correlated with Playwright "
                        "navigation evidence for the exact allowlisted URL. "
                        "Exploitability is not asserted."
                    )
                elif correlation_context:
                    reason = (
                        "Passive security signal correlated with "
                        f"{correlation_context}; no route-to-source causality "
                        "or exploitability is asserted."
                    )
                else:
                    reason = (
                        "Passive security signal preserved without active "
                        "exploitation or unsupported causal claims."
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
        if accessibility is not None:
            summary_parts.append(
                f"axe-core scanned {accessibility.coverage.pages_scanned} "
                f"page(s) and produced {len(accessibility.findings)} "
                "automated accessibility finding group(s)"
            )
            residual_risks.extend(
                accessibility.coverage.manual_criteria_not_checked
            )
            residual_risks.append(
                "Automated axe results cover detectable WCAG A/AA rules only "
                "and do not establish conformance."
            )
        if security is not None:
            if security.coverage.mode == "runtime_passive":
                summary_parts.append(
                    f"Passive security audited "
                    f"{security.coverage.routes_audited} route(s) and produced "
                    f"{len(security.findings)} non-exploitative signal(s)"
                )
            else:
                summary_parts.append(
                    "Security reviewed the bounded repository scope; static "
                    "source, dependency and secret scans were not executed"
                )
            residual_risks.extend(security.residual_risks)
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
