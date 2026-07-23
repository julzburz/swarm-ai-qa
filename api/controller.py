from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Literal
from uuid import UUID, uuid4

from executors.models import RepositoryAnalysisOutputV1
from executors.api import ApiTestExecutor
from executors.browser import BrowserAutomationExecutor
from executors.repository import RepositoryAnalystExecutor
from orchestrator import AgentRegistry, RuleBasedQaDirector, SwarmOrchestrator
from orchestrator.models import RunStateV1
from schemas.mission import SwarmExecutionPlanV1, UserMissionRequestV1
from schemas.common import MissionMode, QualityDomain
from workers.api import SafeHttpApiWorker
from workers.browser import PlaywrightBrowserWorker

from .runtime_reconnaissance import inspect_runtime
from .schemas import RuntimeReconnaissanceV1


class MissingExecutorsError(RuntimeError):
    def __init__(self, agent_ids: list[str]) -> None:
        self.agent_ids = agent_ids
        super().__init__(f"Missing agent executors: {agent_ids}")


class PlanPreviewExpiredError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AdaptivePlanPreview:
    mission: UserMissionRequestV1
    plan: SwarmExecutionPlanV1
    reconnaissance: RepositoryAnalysisOutputV1 | None
    runtime_reconnaissance: RuntimeReconnaissanceV1 | None
    planning_basis: Literal[
        "repository_reconnaissance",
        "runtime_reconnaissance",
        "combined_reconnaissance",
        "runtime_inputs",
        "mission_inputs",
    ]


class RunController:
    """Owns in-process run tasks while durable state remains in RunStore."""

    def __init__(
        self,
        orchestrator: SwarmOrchestrator,
        registry: AgentRegistry,
        director: RuleBasedQaDirector | None = None,
        preview_ttl_seconds: float = 600.0,
    ) -> None:
        if preview_ttl_seconds <= 0:
            raise ValueError("preview_ttl_seconds must be positive")
        self.orchestrator = orchestrator
        self.registry = registry
        self.director = director or RuleBasedQaDirector()
        self.preview_ttl_seconds = preview_ttl_seconds
        self._tasks: dict[UUID, asyncio.Task[RunStateV1]] = {}
        self._previews: dict[
            UUID,
            tuple[float, UserMissionRequestV1, AdaptivePlanPreview],
        ] = {}

    def plan(self, mission: UserMissionRequestV1) -> SwarmExecutionPlanV1:
        return self.director.build_plan(mission)

    async def preview(self, mission: UserMissionRequestV1) -> AdaptivePlanPreview:
        reconnaissance: RepositoryAnalysisOutputV1 | None = None
        runtime_reconnaissance: RuntimeReconnaissanceV1 | None = None
        basis: Literal[
            "repository_reconnaissance",
            "runtime_reconnaissance",
            "combined_reconnaissance",
            "runtime_inputs",
            "mission_inputs",
        ] = "runtime_inputs" if mission.runtime_target is not None else "mission_inputs"

        if (
            mission.repository_target is not None
            and self.registry.contains("repository_analyst")
        ):
            executor = self.registry.get("repository_analyst")
            if isinstance(executor, RepositoryAnalystExecutor):
                reconnaissance = await executor.inspect_target(
                    mission.repository_target,
                    mission.pull_request_number,
                )
                basis = "repository_reconnaissance"

        requested_domains = set(mission.selected_domains)
        for job in mission.requested_jobs:
            requested_domains.update(job.domains)
        browser_executor = (
            self.registry.get("browser_automation_engineer")
            if self.registry.contains("browser_automation_engineer")
            else None
        )
        api_executor = (
            self.registry.get("api_test_engineer")
            if self.registry.contains("api_test_engineer")
            else None
        )
        runtime_reconnaissance_available = (
            mission.runtime_target is not None
            and (
                (
                    (
                        QualityDomain.FUNCTIONAL in requested_domains
                        or mission.mode == MissionMode.FULL_EXAMINATION
                    )
                    and isinstance(
                        browser_executor,
                        BrowserAutomationExecutor,
                    )
                    and isinstance(
                        browser_executor.worker,
                        PlaywrightBrowserWorker,
                    )
                )
                or (
                    QualityDomain.API in requested_domains
                    and isinstance(api_executor, ApiTestExecutor)
                    and isinstance(api_executor.worker, SafeHttpApiWorker)
                )
            )
        )
        if runtime_reconnaissance_available and mission.runtime_target is not None:
            runtime_reconnaissance = await inspect_runtime(
                mission.runtime_target,
                mission.mode,
            )
            if runtime_reconnaissance.planned_paths:
                mission = mission.model_copy(
                    update={
                        "runtime_target": mission.runtime_target.model_copy(
                            update={
                                "allowed_paths": (
                                    runtime_reconnaissance.planned_paths
                                )
                            }
                        )
                    }
                )
            basis = (
                "combined_reconnaissance"
                if reconnaissance is not None
                else "runtime_reconnaissance"
            )

        plan = self.director.build_plan(
            mission,
            project_profile=(
                reconnaissance.project_profile
                if reconnaissance is not None
                else None
            ),
            change_impact=(
                reconnaissance.change_impact
                if reconnaissance is not None
                else None
            ),
        )
        preview = AdaptivePlanPreview(
            mission=mission,
            plan=plan,
            reconnaissance=reconnaissance,
            runtime_reconnaissance=runtime_reconnaissance,
            planning_basis=basis,
        )
        self._previews[mission.mission_id] = (
            time.monotonic(),
            mission.model_copy(deep=True),
            preview,
        )
        while len(self._previews) > 128:
            self._previews.pop(next(iter(self._previews)))
        return preview

    def approved_plan(
        self,
        mission: UserMissionRequestV1,
        approved_plan_id: UUID | None = None,
    ) -> SwarmExecutionPlanV1:
        cached = self._previews.get(mission.mission_id)
        if cached is not None:
            cached_at, cached_mission, preview = cached
            if (
                time.monotonic() - cached_at <= self.preview_ttl_seconds
                and cached_mission == mission
                and (
                    approved_plan_id is None
                    or preview.plan.plan_id == approved_plan_id
                )
            ):
                return preview.plan
            self._previews.pop(mission.mission_id, None)
        if approved_plan_id is not None:
            raise PlanPreviewExpiredError(
                "The approved adaptive plan is unavailable or no longer matches the mission"
            )
        return self.plan(mission)

    def discard_preview(self, mission_id: UUID) -> None:
        self._previews.pop(mission_id, None)

    def missing_executors(self, plan: SwarmExecutionPlanV1) -> list[str]:
        return sorted(plan.selected_agents - self.registry.agent_ids)

    async def start(
        self,
        mission: UserMissionRequestV1,
        plan: SwarmExecutionPlanV1,
    ) -> UUID:
        missing = self.missing_executors(plan)
        if missing:
            raise MissingExecutorsError(missing)

        run_id = uuid4()
        task = asyncio.create_task(
            self.orchestrator.execute(mission, plan, run_id=run_id),
            name=f"api-run:{run_id}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda completed, current=run_id: self._on_done(current, completed))

        # Let execute() persist its initial checkpoint before returning HTTP 202.
        await asyncio.sleep(0)
        return run_id

    def is_active(self, run_id: UUID) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    async def shutdown(self) -> None:
        active_ids = [run_id for run_id, task in self._tasks.items() if not task.done()]
        for run_id in active_ids:
            try:
                await self.orchestrator.cancel(run_id)
            except LookupError:
                pass
        active_tasks = [task for task in self._tasks.values() if not task.done()]
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        self._previews.clear()

    def _on_done(self, run_id: UUID, task: asyncio.Task[RunStateV1]) -> None:
        self._tasks.pop(run_id, None)
        if not task.cancelled():
            task.exception()
