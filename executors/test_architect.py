from __future__ import annotations

from uuid import uuid4

from orchestrator.ports import AgentExecutionContextV1
from schemas.common import QualityDomain
from schemas.evidence import AgentOutputEnvelopeV1
from schemas.execution import (
    CoverageObjectiveV1,
    SpecialistTaskV1,
    TestCaseDesignV1,
    TestPlanV1,
)

from .models import RepositoryAnalysisOutputV1, TestArchitectureOutputV1


PLANNED_AGENT_BY_DOMAIN = {
    QualityDomain.REPOSITORY: "evidence_reporting_analyst",
    QualityDomain.FUNCTIONAL: "browser_automation_engineer",
    QualityDomain.API: "api_test_engineer",
    QualityDomain.SECURITY: "security_test_engineer",
    QualityDomain.ACCESSIBILITY: "accessibility_specialist",
    QualityDomain.PERFORMANCE: "performance_test_engineer",
}


class TestArchitectExecutor:
    agent_id = "test_architect"

    async def execute(self, task: SpecialistTaskV1, context: AgentExecutionContextV1) -> AgentOutputEnvelopeV1:
        source_envelope = next(
            (
                output
                for output in context.dependency_outputs.values()
                if output.agent_id == "repository_analyst"
            ),
            None,
        )
        analysis = (
            RepositoryAnalysisOutputV1.model_validate(source_envelope.output)
            if source_envelope is not None
            else None
        )
        domains = _mission_domains(context)
        objectives = [
            CoverageObjectiveV1(
                objective_id=f"coverage-{domain.value}",
                domain=domain,
                risk_reference=(
                    analysis.change_impact.change_id
                    if analysis is not None and analysis.change_impact
                    else f"profile:{analysis.project_profile.profile_id}"
                    if analysis is not None
                    else f"runtime:{context.mission.runtime_target.target_id}"
                ),
                description=f"Verify evidence and risks for the {domain.value} domain.",
                mandatory=True,
                acceptance_criteria=["Produce schema-valid, evidence-linked observations."],
            )
            for domain in sorted(domains, key=lambda item: item.value)
        ]
        planned_tasks = [
            SpecialistTaskV1(
                task_id=uuid4(),
                agent_id=PLANNED_AGENT_BY_DOMAIN.get(
                    domain,
                    "evidence_reporting_analyst",
                ),
                objective=f"Execute the approved {domain.value} QA objective.",
                domain=domain,
                capability_ids=[f"execute_{domain.value}_objective"],
                risk_refs=[objective.risk_reference],
                estimated_requests=0,
            )
            for domain, objective in zip(sorted(domains, key=lambda item: item.value), objectives)
        ]
        residual = list(analysis.project_profile.unknowns) if analysis is not None else []
        if analysis is None:
            residual.append("Repository stack was not available for runtime-only planning.")
        if (
            analysis is not None
            and analysis.change_impact is None
            and context.mission.pull_request_number is not None
        ):
            residual.append("The pull request contained no changed files in the bounded response.")
        plan = TestPlanV1(
            mission_id=context.mission.mission_id,
            strategy_summary=(
                "Aplicar una estrategia basada en riesgos y permanentemente "
                "read-only. Ejecutar solamente casos automatizados seguros "
                "respaldados por los agentes seleccionados; conservar los "
                "casos negativos, autenticados y UAT como trabajo manual "
                "explícito en lugar de simular resultados."
            ),
            coverage_objectives=objectives,
            tasks=planned_tasks,
            test_cases=_design_test_cases(
                context,
                domains,
                {
                    objective.domain: objective.risk_reference
                    for objective in objectives
                },
            ),
            critical_journeys=_critical_journeys(context, analysis, domains),
            budget=context.mission.budget,
            residual_risks=residual,
        )
        output = TestArchitectureOutputV1(
            test_plan=plan,
            source_profile_id=analysis.project_profile.profile_id if analysis is not None else None,
            source_change_id=(
                analysis.change_impact.change_id
                if analysis is not None and analysis.change_impact
                else None
            ),
        )
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="TestArchitectureOutputV1",
            output=output.model_dump(mode="json"),
            evidence_refs=source_envelope.evidence_refs if source_envelope is not None else [],
        )


def _mission_domains(context: AgentExecutionContextV1) -> set[QualityDomain]:
    mission = context.mission
    domains = set(mission.selected_domains)
    for job in mission.requested_jobs:
        domains.update(job.domains)
    if mission.runtime_target is None:
        domains -= {
            QualityDomain.FUNCTIONAL,
            QualityDomain.API,
            QualityDomain.ACCESSIBILITY,
            QualityDomain.PERFORMANCE,
        }
    return domains or {QualityDomain.REPOSITORY}


def _critical_journeys(
    context: AgentExecutionContextV1,
    analysis: RepositoryAnalysisOutputV1 | None,
    domains: set[QualityDomain],
) -> list[str]:
    target = context.mission.runtime_target
    if target is None or not {
        QualityDomain.FUNCTIONAL,
        QualityDomain.API,
        QualityDomain.ACCESSIBILITY,
    } & domains:
        return []
    candidates = (
        [
            journey
            for surface in analysis.change_impact.impacted_surfaces
            for journey in surface.user_journeys
        ]
        if analysis is not None and analysis.change_impact is not None
        else []
    )
    prioritized = [
        candidate
        for candidate in candidates
        if any(_path_matches(candidate, allowed) for allowed in target.allowed_paths)
    ]
    return list(dict.fromkeys([*prioritized, *target.allowed_paths]))


def _path_matches(path: str, allowed: str) -> bool:
    prefix = "/" + allowed.strip("/")
    return prefix == "/" or path == prefix or path.startswith(prefix + "/")


def _design_test_cases(
    context: AgentExecutionContextV1,
    domains: set[QualityDomain],
    risk_by_domain: dict[QualityDomain, str],
) -> list[TestCaseDesignV1]:
    cases: list[TestCaseDesignV1] = []
    repository = context.mission.repository_target
    runtime = context.mission.runtime_target

    if QualityDomain.REPOSITORY in domains and repository is not None:
        cases.append(
            TestCaseDesignV1(
                case_id="TC-REPOSITORY-001",
                title="Reconocer estructura y stack del repositorio",
                domain=QualityDomain.REPOSITORY,
                test_type="repository",
                priority="high",
                risk_reference=risk_by_domain[QualityDomain.REPOSITORY],
                preconditions=[
                    "El repositorio GitHub público está autorizado para lectura."
                ],
                steps=[
                    "Inspeccionar metadata, árbol y manifests permitidos.",
                    "Separar componentes, lenguajes y frameworks respaldados por evidencia.",
                ],
                expected_result=(
                    "El perfil tecnológico y sus incertidumbres quedan "
                    "documentados sin ejecutar comandos ni modificar archivos."
                ),
                gherkin=_gherkin(
                    "Reconocimiento read-only del repositorio",
                    f'el repositorio "{repository.repository_id}" está autorizado',
                    "Repository Analyst inspecciona únicamente evidencia permitida",
                    "el stack y los componentes quedan documentados sin cambios",
                ),
                execution_mode="automated",
                assigned_agent="repository_analyst",
                target_reference=repository.repository_id,
            )
        )

    if runtime is None:
        if QualityDomain.SECURITY in domains and repository is not None:
            cases.append(
                TestCaseDesignV1(
                    case_id="TC-SECURITY-001",
                    title="Definir alcance de seguridad del repositorio",
                    domain=QualityDomain.SECURITY,
                    test_type="security",
                    priority="high",
                    risk_reference=risk_by_domain[QualityDomain.SECURITY],
                    preconditions=[
                        "Existe un snapshot read-only del repositorio."
                    ],
                    steps=[
                        "Revisar el perfil y cambio capturados.",
                        "Declarar las comprobaciones estáticas que permanecen pendientes.",
                    ],
                    expected_result=(
                        "El alcance queda documentado sin afirmar que se "
                        "ejecutó un escaneo de código o dependencias."
                    ),
                    gherkin=_gherkin(
                        "Alcance de seguridad sin escaneo simulado",
                        "existe evidencia read-only del repositorio",
                        "Security Test Engineer revisa el alcance disponible",
                        "los controles no ejecutados quedan explícitamente pendientes",
                    ),
                    execution_mode="automated",
                    assigned_agent="security_test_engineer",
                    target_reference=repository.repository_id,
                )
            )
        return cases

    base_url = str(runtime.base_url).rstrip("/")
    for index, path in enumerate(runtime.allowed_paths, start=1):
        url = base_url + (path if path.startswith("/") else f"/{path}")
        suffix = f"{index:03d}"
        if QualityDomain.FUNCTIONAL in domains:
            cases.extend(
                [
                    TestCaseDesignV1(
                        case_id=f"TC-FUNCTIONAL-{suffix}",
                        title=f"Smoke funcional de {path}",
                        domain=QualityDomain.FUNCTIONAL,
                        test_type="smoke",
                        priority="critical",
                        risk_reference=risk_by_domain[
                            QualityDomain.FUNCTIONAL
                        ],
                        preconditions=[
                            "La ruta pertenece al allowlist aprobado.",
                            "La navegación no requiere una acción irreversible.",
                        ],
                        steps=[
                            f"Navegar a {path} en un contexto Chromium aislado.",
                            "Observar HTTP, errores de página, consola y red.",
                            "Capturar screenshot y trace como evidencia.",
                        ],
                        expected_result=(
                            "La página carga sin error HTTP ni excepción "
                            "de navegador observable."
                        ),
                        gherkin=_gherkin(
                            f"Smoke funcional de {path}",
                            f'la ruta "{path}" está autorizada',
                            "Browser Automation navega en modo read-only",
                            "la página carga sin errores observables",
                        ),
                        execution_mode="automated",
                        assigned_agent="browser_automation_engineer",
                        target_reference=url,
                    ),
                    TestCaseDesignV1(
                        case_id=f"TC-NEGATIVE-{suffix}",
                        title=f"Validar estados negativos e interacción en {path}",
                        domain=QualityDomain.FUNCTIONAL,
                        test_type="negative",
                        priority="high",
                        risk_reference=risk_by_domain[
                            QualityDomain.FUNCTIONAL
                        ],
                        preconditions=[
                            "Existe un entorno de staging y datos sintéticos aprobados."
                        ],
                        steps=[
                            "Ejecutar entradas inválidas y límites de negocio.",
                            "Verificar mensajes, foco y conservación segura del estado.",
                        ],
                        expected_result=(
                            "Las entradas inválidas se rechazan con mensajes "
                            "claros y sin efectos secundarios."
                        ),
                        gherkin=_gherkin(
                            f"Comportamiento negativo de {path}",
                            "existen datos sintéticos inválidos autorizados",
                            "un QA ejecuta el flujo negativo",
                            "el sistema rechaza la acción sin efectos secundarios",
                        ),
                        execution_mode="manual",
                        assigned_agent="manual_qa_reviewer",
                        target_reference=url,
                    ),
                ]
            )
            if (
                runtime.allow_form_submission
                and runtime.environment.value in {"staging", "sandbox"}
            ):
                cases.append(
                    TestCaseDesignV1(
                        case_id=f"TC-INTERACTION-{suffix}",
                        title=f"Flujo interactivo seguro de {path}",
                        domain=QualityDomain.FUNCTIONAL,
                        test_type="functional",
                        priority="high",
                        risk_reference=risk_by_domain[
                            QualityDomain.FUNCTIONAL
                        ],
                        preconditions=[
                            "El target es staging o sandbox.",
                            "El usuario autorizó interacciones seguras.",
                            "Las rutas destino pertenecen al allowlist.",
                        ],
                        steps=[
                            "Descubrir un enlace interno no destructivo.",
                            "Ejecutar el click y validar el destino same-origin.",
                            "Completar campos no sensibles con datos sintéticos.",
                            "Enviar únicamente formularios GET autorizados.",
                        ],
                        expected_result=(
                            "Las interacciones permitidas completan el flujo "
                            "sin requests mutantes ni acciones destructivas."
                        ),
                        gherkin=_gherkin(
                            f"Interacción funcional segura de {path}",
                            "el target staging está autorizado para interacción",
                            "Browser Automation ejecuta enlaces y formularios GET seguros",
                            "el flujo permanece en el allowlist y no muta datos",
                        ),
                        execution_mode="automated",
                        assigned_agent="browser_automation_engineer",
                        target_reference=url,
                    )
                )
        if QualityDomain.ACCESSIBILITY in domains:
            cases.extend(
                [
                    TestCaseDesignV1(
                        case_id=f"TC-ACCESSIBILITY-{suffix}",
                        title=f"Escaneo automatizado WCAG de {path}",
                        domain=QualityDomain.ACCESSIBILITY,
                        test_type="accessibility",
                        priority="high",
                        risk_reference=risk_by_domain[
                            QualityDomain.ACCESSIBILITY
                        ],
                        preconditions=[
                            "La página pública puede cargarse sin autenticación."
                        ],
                        steps=[
                            f"Navegar a {path} con las políticas de red aprobadas.",
                            "Ejecutar reglas axe-core WCAG A/AA.",
                        ],
                        expected_result=(
                            "No se detectan violaciones automatizables en el "
                            "estado inspeccionado."
                        ),
                        gherkin=_gherkin(
                            f"Accesibilidad automatizada de {path}",
                            "la página autorizada está cargada",
                            "Accessibility Specialist ejecuta axe-core",
                            "las barreras detectables quedan respaldadas por evidencia",
                        ),
                        execution_mode="automated",
                        assigned_agent="accessibility_specialist",
                        target_reference=url,
                    ),
                    TestCaseDesignV1(
                        case_id=f"TC-A11Y-MANUAL-{suffix}",
                        title=f"Teclado y lector de pantalla en {path}",
                        domain=QualityDomain.ACCESSIBILITY,
                        test_type="uat",
                        priority="medium",
                        risk_reference=risk_by_domain[
                            QualityDomain.ACCESSIBILITY
                        ],
                        preconditions=[
                            "Un evaluador humano dispone de teclado y lector de pantalla."
                        ],
                        steps=[
                            "Recorrer el flujo completo solo con teclado.",
                            "Validar orden, foco, anuncios y comprensión con lector de pantalla.",
                        ],
                        expected_result=(
                            "El flujo es operable y comprensible mediante "
                            "tecnologías de asistencia."
                        ),
                        gherkin=_gherkin(
                            f"Verificación manual de accesibilidad en {path}",
                            "un evaluador usa tecnologías de asistencia",
                            "recorre el flujo sin mouse",
                            "el contenido mantiene foco, orden y significado",
                        ),
                        execution_mode="manual",
                        assigned_agent="manual_accessibility_reviewer",
                        target_reference=url,
                    ),
                ]
            )
        if QualityDomain.SECURITY in domains:
            cases.extend(
                [
                    TestCaseDesignV1(
                        case_id=f"TC-SECURITY-{suffix}",
                        title=f"Auditoría pasiva de seguridad de {path}",
                        domain=QualityDomain.SECURITY,
                        test_type="security",
                        priority="high",
                        risk_reference=risk_by_domain[
                            QualityDomain.SECURITY
                        ],
                        preconditions=[
                            "La ruta está autorizada para una solicitud GET acotada."
                        ],
                        steps=[
                            "Observar HTTPS/TLS, cabeceras, CORS y cookies redactadas.",
                            "Comparar la respuesta con la política pasiva.",
                        ],
                        expected_result=(
                            "La respuesta no presenta señales pasivas de "
                            "configuración defensiva ausente."
                        ),
                        gherkin=_gherkin(
                            f"Seguridad pasiva de {path}",
                            f'la ruta "{path}" permite inspección read-only',
                            "Security Test Engineer observa la respuesta sin explotar",
                            "las señales defensivas quedan documentadas",
                        ),
                        execution_mode="automated",
                        assigned_agent="security_test_engineer",
                        target_reference=url,
                    ),
                    TestCaseDesignV1(
                        case_id=f"TC-SECURITY-MANUAL-{suffix}",
                        title=f"Autorización y reglas de negocio de {path}",
                        domain=QualityDomain.SECURITY,
                        test_type="negative",
                        priority="high",
                        risk_reference=risk_by_domain[
                            QualityDomain.SECURITY
                        ],
                        preconditions=[
                            "Existe staging, una cuenta de prueba y autorización explícita."
                        ],
                        steps=[
                            "Intentar accesos con roles de prueba permitidos.",
                            "Verificar límites de autorización sin explotar vulnerabilidades.",
                        ],
                        expected_result=(
                            "Cada rol accede únicamente a operaciones y datos autorizados."
                        ),
                        gherkin=_gherkin(
                            f"Autorización de negocio en {path}",
                            "existen roles sintéticos autorizados en staging",
                            "un QA intenta operaciones fuera de su rol",
                            "el sistema bloquea el acceso sin revelar datos",
                        ),
                        execution_mode="manual",
                        assigned_agent="manual_security_reviewer",
                        target_reference=url,
                    ),
                ]
            )
        if QualityDomain.PERFORMANCE in domains:
            cases.extend(
                [
                    TestCaseDesignV1(
                        case_id=f"TC-PERFORMANCE-{suffix}",
                        title=f"Performance smoke de laboratorio de {path}",
                        domain=QualityDomain.PERFORMANCE,
                        test_type="performance",
                        priority="medium",
                        risk_reference=risk_by_domain[
                            QualityDomain.PERFORMANCE
                        ],
                        preconditions=[
                            "La ruta admite navegación pública read-only."
                        ],
                        steps=[
                            "Ejecutar tres contextos Chromium aislados.",
                            "Medir LCP, CLS, TTFB, carga y transferencia.",
                            "Reportar p75, mediana, varianza y contexto.",
                        ],
                        expected_result=(
                            "Las mediciones quedan registradas como señales "
                            "de laboratorio, no como regresión sin baseline."
                        ),
                        gherkin=_gherkin(
                            f"Performance de laboratorio de {path}",
                            "la ruta está autorizada para un smoke single-user",
                            "Performance Test Engineer ejecuta tres muestras aisladas",
                            "las métricas quedan contextualizadas sin generar carga",
                        ),
                        execution_mode="automated",
                        assigned_agent="performance_test_engineer",
                        target_reference=url,
                    ),
                    TestCaseDesignV1(
                        case_id=f"TC-PERF-FIELD-{suffix}",
                        title=f"Experiencia real e interacción de {path}",
                        domain=QualityDomain.PERFORMANCE,
                        test_type="uat",
                        priority="low",
                        risk_reference=risk_by_domain[
                            QualityDomain.PERFORMANCE
                        ],
                        preconditions=[
                            "Existe telemetría de usuarios consentida y representativa."
                        ],
                        steps=[
                            "Revisar Core Web Vitals de campo al percentil 75.",
                            "Validar INP mediante interacciones representativas.",
                        ],
                        expected_result=(
                            "La experiencia real cumple los objetivos acordados "
                            "para usuarios y dispositivos representativos."
                        ),
                        gherkin=_gherkin(
                            f"Performance real de {path}",
                            "existen datos de campo representativos y consentidos",
                            "un responsable revisa Core Web Vitals e INP",
                            "la decisión usa datos reales y no solo laboratorio",
                        ),
                        execution_mode="manual",
                        assigned_agent="performance_owner",
                        target_reference=url,
                    ),
                ]
            )
        if QualityDomain.API in domains and index == 1:
            cases.append(
                TestCaseDesignV1(
                    case_id="TC-API-001",
                    title="Descubrir y validar el contrato API autorizado",
                    domain=QualityDomain.API,
                    test_type="api",
                    priority="medium",
                    risk_reference=risk_by_domain[QualityDomain.API],
                    preconditions=[
                        "Existe un contrato OpenAPI o endpoint GET autorizado."
                    ],
                    steps=[
                        "Descubrir operaciones seguras del contrato.",
                        "Validar status, headers y schema sin mutar datos.",
                    ],
                    expected_result=(
                        "Las operaciones GET cumplen el contrato documentado."
                    ),
                    gherkin=_gherkin(
                        f"Contrato API de {path}",
                        "existe un contrato o endpoint GET autorizado",
                        "API Test Engineer valida una respuesta read-only",
                        "status y schema cumplen el contrato",
                    ),
                    execution_mode="automated",
                    assigned_agent="api_test_engineer",
                    target_reference=url,
                )
            )
    return cases


def _gherkin(
    scenario: str,
    given: str,
    when: str,
    then: str,
) -> str:
    scenario = _single_line(scenario)
    given = _single_line(given)
    when = _single_line(when)
    then = _single_line(then)
    return (
        "# language: es\n"
        f"Característica: {scenario}\n"
        f"  Escenario: {scenario}\n"
        f"    Dado {given}\n"
        f"    Cuando {when}\n"
        f"    Entonces {then}"
    )


def _single_line(value: str) -> str:
    return " ".join(value.split())
