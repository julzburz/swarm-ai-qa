from __future__ import annotations

from uuid import uuid4

from orchestrator.ports import AgentExecutionContextV1
from schemas.common import QualityDomain
from schemas.evidence import AgentOutputEnvelopeV1
from schemas.execution import CoverageObjectiveV1, SpecialistTaskV1, TestPlanV1

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
                "Use repository metadata and captured manifests as the evidence baseline; "
                "do not execute discovered project commands without separate authorization."
            ),
            coverage_objectives=objectives,
            tasks=planned_tasks,
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
    return domains or {QualityDomain.REPOSITORY}


def _critical_journeys(
    context: AgentExecutionContextV1,
    analysis: RepositoryAnalysisOutputV1 | None,
    domains: set[QualityDomain],
) -> list[str]:
    target = context.mission.runtime_target
    if target is None or QualityDomain.FUNCTIONAL not in domains:
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
