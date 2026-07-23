from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from orchestrator import AgentRegistry, RuleBasedQaDirector, SwarmOrchestrator
from orchestrator.models import RunStateV1
from schemas.mission import SwarmExecutionPlanV1, UserMissionRequestV1


class MissingExecutorsError(RuntimeError):
    def __init__(self, agent_ids: list[str]) -> None:
        self.agent_ids = agent_ids
        super().__init__(f"Missing agent executors: {agent_ids}")


class RunController:
    """Owns in-process run tasks while durable state remains in RunStore."""

    def __init__(
        self,
        orchestrator: SwarmOrchestrator,
        registry: AgentRegistry,
        director: RuleBasedQaDirector | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.registry = registry
        self.director = director or RuleBasedQaDirector()
        self._tasks: dict[UUID, asyncio.Task[RunStateV1]] = {}

    def plan(self, mission: UserMissionRequestV1) -> SwarmExecutionPlanV1:
        return self.director.build_plan(mission)

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

    def _on_done(self, run_id: UUID, task: asyncio.Task[RunStateV1]) -> None:
        self._tasks.pop(run_id, None)
        if not task.cancelled():
            task.exception()
