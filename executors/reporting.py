from __future__ import annotations

from orchestrator.ports import AgentExecutionContextV1
from schemas.common import QualityDomain
from schemas.evidence import AgentOutputEnvelopeV1, CorrelatedFindingV1
from schemas.execution import (
    CoverageSummaryV1,
    SpecialistTaskV1,
    TestCaseDesignV1,
    TestCaseExecutionV1,
)
from schemas.reporting import QaRunReportV1
from schemas.specialists import (
    AccessibilityAgentOutputV1,
    BrowserAgentOutputV1,
    PerformanceAgentOutputV1,
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
        performance_envelope = outputs.get("performance_test_engineer")
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
        performance = (
            PerformanceAgentOutputV1.model_validate(
                performance_envelope.output
            )
            if performance_envelope is not None
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
        if performance is not None:
            executed_domains.add(QualityDomain.PERFORMANCE)
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
        if performance is not None:
            for finding in performance.findings:
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
                        "Lab performance signal correlated with Playwright "
                        "navigation evidence for the exact allowlisted URL. "
                        "This is not a field-data or regression claim."
                    )
                elif correlation_context:
                    reason = (
                        "Lab performance signal correlated with "
                        f"{correlation_context}; no route-to-source causality "
                        "or regression is asserted."
                    )
                else:
                    reason = (
                        "Lab performance signal preserved without claiming "
                        "field performance or a regression."
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
        if performance is not None:
            summary_parts.append(
                f"Performance measured {performance.coverage.pages_measured} "
                f"page(s) with {performance.coverage.successful_samples} "
                "isolated single-user lab sample(s); no load test was performed"
            )
            residual_risks.extend(performance.residual_risks)
        if repository is not None and browser is not None:
            residual_risks.append(
                "Repository and runtime evidence are correlated by mission and "
                "risk context; route-to-source causality remains unproven."
            )
        test_case_results = _test_case_results(
            plan.test_cases,
            outputs,
            repository=repository,
            browser=browser,
            accessibility=accessibility,
            security=security,
            performance=performance,
        )
        automated_completed = sum(
            result.status
            in {"passed", "failed", "blocked", "observed"}
            for result in test_case_results
        )
        manual_required = sum(
            result.status == "manual_required"
            for result in test_case_results
        )
        if test_case_results:
            summary_parts.append(
                f"Test Design Studio trazó {len(test_case_results)} caso(s); "
                f"{automated_completed} caso(s) automatizados alcanzaron un "
                f"resultado y {manual_required} requieren ejecución humana"
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
            test_case_results=test_case_results,
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


def _test_case_results(
    test_cases: list[TestCaseDesignV1],
    outputs: dict[str, AgentOutputEnvelopeV1],
    *,
    repository,
    browser,
    accessibility,
    security,
    performance,
) -> list[TestCaseExecutionV1]:
    results: list[TestCaseExecutionV1] = []
    for test_case in test_cases:
        if test_case.execution_mode == "manual":
            results.append(
                TestCaseExecutionV1(
                    case_id=test_case.case_id,
                    status="manual_required",
                    observation=(
                        "Diseñado y conservado para ejecución humana; no se "
                        "afirma un resultado ni evidencia automatizada."
                    ),
                )
            )
            continue

        envelope = outputs.get(test_case.assigned_agent)
        if envelope is None:
            results.append(
                TestCaseExecutionV1(
                    case_id=test_case.case_id,
                    status="not_executed",
                    observation=(
                        f"{test_case.assigned_agent} no produjo una salida "
                        "para esta ejecución."
                    ),
                )
            )
            continue

        if test_case.domain == QualityDomain.REPOSITORY:
            evidence = _unique_evidence(envelope.evidence_refs)
            if repository is not None and evidence:
                results.append(
                    TestCaseExecutionV1(
                        case_id=test_case.case_id,
                        status="observed",
                        observation=(
                            "La estructura y tecnología del repositorio "
                            "quedaron documentadas sin ejecutar comandos."
                        ),
                        executed_by=test_case.assigned_agent,
                        evidence_refs=evidence,
                    )
                )
            else:
                results.append(
                    TestCaseExecutionV1(
                        case_id=test_case.case_id,
                        status="blocked",
                        observation=(
                            "El análisis del repositorio no proporcionó "
                            "evidencia material para este caso."
                        ),
                        executed_by=test_case.assigned_agent,
                    )
                )
            continue

        if test_case.domain == QualityDomain.FUNCTIONAL:
            journey = next(
                (
                    item
                    for item in browser.journeys
                    if _same_location(
                        item.environment_url,
                        test_case.target_reference,
                    )
                ),
                None,
            ) if browser is not None else None
            if journey is None:
                results.append(
                    TestCaseExecutionV1(
                        case_id=test_case.case_id,
                        status="blocked",
                        observation=(
                            "Ningún journey de Browser coincidió con el target "
                            "planificado."
                        ),
                        executed_by=test_case.assigned_agent,
                    )
                )
                continue
            related = [
                finding
                for finding in browser.findings
                if test_case.target_reference
                and any(
                    _same_location(location, test_case.target_reference)
                    for location in finding.affected_locations
                )
            ]
            results.append(
                TestCaseExecutionV1(
                    case_id=test_case.case_id,
                    status=journey.status,
                    observation=(
                        f"El journey de Browser terminó con estado "
                        f"{journey.status} y {len(related)} finding(s) enlazados."
                    ),
                    executed_by=test_case.assigned_agent,
                    evidence_refs=journey.evidence_refs,
                    finding_ids=[
                        finding.finding_id for finding in related
                    ],
                )
            )
            continue

        if test_case.domain == QualityDomain.ACCESSIBILITY:
            related = _findings_for_target(
                accessibility.findings if accessibility is not None else [],
                test_case.target_reference,
            )
            evidence = _unique_evidence(envelope.evidence_refs)
            if accessibility is None or not evidence:
                status = "blocked"
                observation = (
                    "Accessibility no proporcionó evidencia material."
                )
            else:
                status = "failed" if related else "passed"
                observation = (
                    f"axe completó la cobertura automatizada con "
                    f"{len(related)} grupo(s) de violaciones enlazados al "
                    "target. No se afirma conformidad WCAG manual."
                )
            results.append(
                TestCaseExecutionV1(
                    case_id=test_case.case_id,
                    status=status,
                    observation=observation,
                    executed_by=test_case.assigned_agent,
                    evidence_refs=evidence,
                    finding_ids=[
                        finding.finding_id for finding in related
                    ],
                )
            )
            continue

        if test_case.domain == QualityDomain.SECURITY:
            related = _findings_for_target(
                security.findings if security is not None else [],
                test_case.target_reference,
            )
            evidence = _unique_evidence(envelope.evidence_refs)
            if security is None or not evidence:
                status = "blocked"
                observation = (
                    "Security no proporcionó evidencia material."
                )
            elif security.coverage.mode == "repository_scope_only":
                status = "observed"
                observation = (
                    "El alcance de seguridad del repositorio quedó documentado; "
                    "los escaneos de código, dependencias y secretos siguen pendientes."
                )
            else:
                status = "failed" if related else "passed"
                observation = (
                    f"La auditoría pasiva terminó con {len(related)} señal(es) "
                    "enlazadas al target. No se afirma explotabilidad."
                )
            results.append(
                TestCaseExecutionV1(
                    case_id=test_case.case_id,
                    status=status,
                    observation=observation,
                    executed_by=test_case.assigned_agent,
                    evidence_refs=evidence,
                    finding_ids=[
                        finding.finding_id for finding in related
                    ],
                )
            )
            continue

        if test_case.domain == QualityDomain.PERFORMANCE:
            related = _findings_for_target(
                performance.findings if performance is not None else [],
                test_case.target_reference,
            )
            evidence = _unique_evidence(envelope.evidence_refs)
            if (
                performance is None
                or performance.coverage.successful_samples == 0
                or not evidence
            ):
                status = "blocked"
                observation = (
                    "Performance smoke no produjo una muestra exitosa "
                    "respaldada por evidencia."
                )
            else:
                status = "observed"
                observation = (
                    f"Las mediciones single-user terminaron con "
                    f"{len(related)} señal(es) de umbral. No se afirma "
                    "performance real ni regresión."
                )
            results.append(
                TestCaseExecutionV1(
                    case_id=test_case.case_id,
                    status=status,
                    observation=observation,
                    executed_by=test_case.assigned_agent,
                    evidence_refs=evidence,
                    finding_ids=[
                        finding.finding_id for finding in related
                    ],
                )
            )
            continue

        results.append(
            TestCaseExecutionV1(
                case_id=test_case.case_id,
                status="not_executed",
                observation=(
                    "El caso está diseñado, pero este dominio todavía no "
                    "dispone de un adaptador de resultados."
                ),
            )
        )
    return results


def _findings_for_target(findings, target_reference):
    return [
        finding
        for finding in findings
        if target_reference
        and any(
            _same_location(location, target_reference)
            for location in finding.affected_locations
        )
    ]


def _same_location(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    return left.rstrip("/") == right.rstrip("/")
