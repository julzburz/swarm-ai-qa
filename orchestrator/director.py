from __future__ import annotations

from uuid import UUID

from schemas.common import MissionMode, QualityDomain
from schemas.execution import SpecialistTaskV1
from schemas.mission import SwarmExecutionPlanV1, UserMissionRequestV1
from schemas.project import ChangeImpactMapV1, ProjectProfileV1


DOMAIN_AGENT: dict[QualityDomain, tuple[str, list[str]]] = {
    QualityDomain.FUNCTIONAL: (
        "browser_automation_engineer",
        ["navigate_flow", "capture_trace", "capture_screenshot"],
    ),
    QualityDomain.API: (
        "api_test_engineer",
        ["discover_api_contract", "validate_response_schema"],
    ),
    QualityDomain.SECURITY: (
        "security_test_engineer",
        ["static_security_scan", "secret_scan", "header_audit"],
    ),
    QualityDomain.ACCESSIBILITY: (
        "accessibility_specialist",
        ["run_axe_audit", "request_keyboard_navigation_check"],
    ),
    QualityDomain.PERFORMANCE: (
        "performance_test_engineer",
        ["run_lighthouse_audit", "run_http_smoke_test"],
    ),
}


class RuleBasedQaDirector:
    """Planner determinista inicial; el LLM podrá proponer, estas reglas validan."""

    def build_plan(
        self,
        mission: UserMissionRequestV1,
        project_profile: ProjectProfileV1 | None = None,
        change_impact: ChangeImpactMapV1 | None = None,
    ) -> SwarmExecutionPlanV1:
        domains = self._applicable_domains(mission)
        tasks: list[SpecialistTaskV1] = []
        reasons: dict[str, str] = {}
        prerequisite_ids: list[UUID] = []

        if mission.repository_target is not None:
            repository_task = SpecialistTaskV1(
                agent_id="repository_analyst",
                objective="Confirmar perfil tecnológico y mapa de impacto del cambio.",
                domain=QualityDomain.REPOSITORY,
                capability_ids=["inspect_diff", "detect_project_components", "build_dependency_map"],
                risk_refs=[f"mission:{mission.mission_id}:project-intelligence"],
                estimated_requests=1,
            )
            tasks.append(repository_task)
            prerequisite_ids.append(repository_task.task_id)
            reasons[repository_task.agent_id] = (
                "El repositorio requiere reconocimiento tecnológico y análisis del cambio."
            )

        architect_task = SpecialistTaskV1(
            agent_id="test_architect",
            objective="Convertir riesgos y alcance en criterios y estrategia de prueba.",
            domain=QualityDomain.REPOSITORY,
            capability_ids=["select_test_layers", "define_critical_journeys"],
            risk_refs=[f"mission:{mission.mission_id}:test-strategy"],
            depends_on=list(prerequisite_ids),
            estimated_requests=0,
        )
        tasks.append(architect_task)
        reasons[architect_task.agent_id] = "Toda ejecución necesita una estrategia trazable basada en riesgo."

        specialist_ids: list[UUID] = []
        for domain in sorted(domains, key=lambda value: value.value):
            mapping = DOMAIN_AGENT.get(domain)
            if mapping is None:
                continue
            agent_id, capabilities = mapping
            dependencies = [architect_task.task_id]
            if domain == QualityDomain.SECURITY:
                dependencies = list(
                    dict.fromkeys([*prerequisite_ids, *dependencies])
                )
            task = SpecialistTaskV1(
                agent_id=agent_id,
                objective=self._objective_for(domain, mission),
                domain=domain,
                capability_ids=capabilities,
                risk_refs=self._risk_refs(domain, mission, change_impact),
                depends_on=dependencies,
                estimated_requests=self._request_estimate(domain),
            )
            tasks.append(task)
            specialist_ids.append(task.task_id)
            reasons[agent_id] = f"La misión incluye el dominio {domain.value}."

        evidence_dependencies = list(
            dict.fromkeys(
                [
                    *prerequisite_ids,
                    architect_task.task_id,
                    *specialist_ids,
                ]
            )
        )
        report_task = SpecialistTaskV1(
            agent_id="evidence_reporting_analyst",
            objective="Normalizar evidencia, correlacionar findings y preparar el reporte.",
            domain=QualityDomain.REPOSITORY,
            capability_ids=["normalize_finding", "correlate_evidence", "publish_run_report"],
            risk_refs=[f"mission:{mission.mission_id}:evidence"],
            depends_on=evidence_dependencies,
            estimated_requests=0,
        )
        tasks.append(report_task)
        reasons[report_task.agent_id] = "Toda afirmación material debe quedar respaldada y correlacionada."

        release_required = mission.request_release_decision is True or (
            mission.mode == MissionMode.FULL_EXAMINATION
        )
        if release_required:
            release_task = SpecialistTaskV1(
                agent_id="release_manager",
                objective="Aplicar gates y emitir una recomendación explicable de release.",
                domain=QualityDomain.REPOSITORY,
                capability_ids=["evaluate_release_gates", "calculate_release_confidence"],
                risk_refs=[f"mission:{mission.mission_id}:release"],
                depends_on=[report_task.task_id],
                estimated_requests=0,
            )
            tasks.append(release_task)
            reasons[release_task.agent_id] = "La misión solicita una decisión de release."

        estimated_requests = sum(task.estimated_requests for task in tasks)
        if estimated_requests > mission.budget.max_requests:
            raise ValueError(
                f"Plan requires {estimated_requests} requests but budget allows "
                f"{mission.budget.max_requests}"
            )

        restrictions: list[str] = []
        if mission.runtime_target and mission.runtime_target.environment.value == "production":
            restrictions.extend(
                [
                    "No load, stress or chaos testing.",
                    "Only allowlisted routes and bounded safe actions.",
                    "Authenticated flows require a referenced test account.",
                ]
            )

        return SwarmExecutionPlanV1(
            mission_id=mission.mission_id,
            summary=self._summary(mission, domains, project_profile),
            tasks=tasks,
            selected_agents=set(reasons),
            agent_selection_reasons=reasons,
            estimated_duration_seconds=max(60, 30 * len(tasks)),
            estimated_requests=estimated_requests,
            production_restrictions=restrictions,
            requires_approval=True,
        )

    def _applicable_domains(self, mission: UserMissionRequestV1) -> set[QualityDomain]:
        if mission.mode == MissionMode.QUICK_TASK:
            requested = {domain for job in mission.requested_jobs for domain in job.domains}
        elif mission.mode == MissionMode.TARGETED_EXAMINATION:
            requested = set(mission.selected_domains)
        else:
            requested = {QualityDomain.SECURITY}
            if mission.runtime_target is not None:
                requested.update(
                    {
                        QualityDomain.FUNCTIONAL,
                        QualityDomain.ACCESSIBILITY,
                        QualityDomain.PERFORMANCE,
                        QualityDomain.API,
                    }
                )

        if mission.runtime_target is None:
            requested -= {
                QualityDomain.FUNCTIONAL,
                QualityDomain.ACCESSIBILITY,
                QualityDomain.PERFORMANCE,
            }
        if mission.repository_target is None and mission.runtime_target is None:
            requested.discard(QualityDomain.SECURITY)
        return requested

    def _objective_for(self, domain: QualityDomain, mission: UserMissionRequestV1) -> str:
        return f"Ejecutar evaluación {domain.value} para: {mission.objective}"

    def _risk_refs(
        self,
        domain: QualityDomain,
        mission: UserMissionRequestV1,
        impact: ChangeImpactMapV1 | None,
    ) -> list[str]:
        refs = [f"mission:{mission.mission_id}:{domain.value}"]
        if impact is not None:
            refs.extend(
                f"impact:{surface.surface_id}"
                for surface in impact.impacted_surfaces
                if surface.risk_hypotheses
            )
        return refs

    def _request_estimate(self, domain: QualityDomain) -> int:
        return {
            QualityDomain.FUNCTIONAL: 30,
            QualityDomain.API: 20,
            QualityDomain.SECURITY: 10,
            QualityDomain.ACCESSIBILITY: 15,
            QualityDomain.PERFORMANCE: 15,
        }.get(domain, 0)

    def _summary(
        self,
        mission: UserMissionRequestV1,
        domains: set[QualityDomain],
        profile: ProjectProfileV1 | None,
    ) -> str:
        stack = "stack pendiente de confirmar"
        if profile and profile.components:
            names = sorted(
                {
                    technology.name
                    for component in profile.components
                    for technology in component.languages + component.frameworks
                }
            )
            if names:
                stack = ", ".join(names)
        domain_text = ", ".join(sorted(domain.value for domain in domains)) or "evidencia solicitada"
        return f"Misión {mission.mode.value} sobre {stack}; dominios: {domain_text}."
