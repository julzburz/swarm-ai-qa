from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from schemas.common import TaskStatus
from schemas.evidence import AgentOutputEnvelopeV1
from schemas.execution import SpecialistTaskV1
from schemas.mission import SwarmExecutionPlanV1, UserMissionRequestV1

from .events import EventStream
from .models import (
    RunEventType,
    RunEventV1,
    RunStateV1,
    RunStatus,
    TaskExecutionRecordV1,
)
from .ports import AgentExecutionContextV1, DependencyFailureV1
from .registry import AgentRegistry
from .store import RunStore


@dataclass(slots=True)
class _TaskOutcome:
    attempts: int
    output: AgentOutputEnvelopeV1 | None = None
    error_class: str | None = None
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.output is not None


class SwarmOrchestrator:
    def __init__(
        self,
        registry: AgentRegistry,
        store: RunStore,
        events: EventStream | None = None,
        max_retries: int = 1,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.registry = registry
        self.store = store
        self.events = events or EventStream(store)
        self.max_retries = max_retries
        self._cancel_events: dict[UUID, asyncio.Event] = {}

    async def execute(
        self,
        mission: UserMissionRequestV1,
        plan: SwarmExecutionPlanV1,
        run_id: UUID | None = None,
    ) -> RunStateV1:
        self._validate_plan(mission, plan)
        now = datetime.now(timezone.utc)
        records = {
            str(task.task_id): TaskExecutionRecordV1(
                task_id=task.task_id,
                agent_id=task.agent_id,
            )
            for task in plan.tasks
        }
        state = RunStateV1(
            run_id=run_id or uuid4(),
            mission=mission,
            plan=plan,
            status=RunStatus.CREATED,
            task_records=records,
            created_at=now,
            updated_at=now,
        )
        cancel_event = asyncio.Event()
        self._cancel_events[state.run_id] = cancel_event
        self.store.save_run(state)
        await self._publish(
            state,
            RunEventType.RUN_CREATED,
            "QA run creado.",
            payload={"mission_id": str(mission.mission_id)},
        )

        state = self._with_status(state, RunStatus.PLANNED)
        await self._publish(
            state,
            RunEventType.RUN_PLANNED,
            "Plan validado y listo para ejecución.",
            payload={
                "task_count": len(plan.tasks),
                "selected_agents": sorted(plan.selected_agents),
            },
        )
        state = self._with_status(state, RunStatus.RUNNING)
        await self._publish(state, RunEventType.RUN_STARTED, "Ejecución del enjambre iniciada.")

        active: dict[asyncio.Task[_TaskOutcome], SpecialistTaskV1] = {}
        tasks_by_id = {task.task_id: task for task in plan.tasks}

        try:
            while not self._all_terminal(state):
                if cancel_event.is_set():
                    state = await self._cancel_active_and_pending(state, active)
                    return state

                state = await self._skip_tasks_with_failed_dependencies(state, tasks_by_id)
                capacity = mission.budget.max_parallel_tasks - len(active)
                if capacity > 0:
                    runnable = self._runnable_tasks(state, plan.tasks)
                    for task in runnable[:capacity]:
                        dependency_outputs = self._dependency_outputs(state, task)
                        dependency_failures = self._dependency_failures(
                            state,
                            task,
                        )
                        active_task = asyncio.create_task(
                            self._run_task(
                                state.run_id,
                                mission,
                                task,
                                dependency_outputs,
                                dependency_failures,
                            ),
                            name=f"{state.run_id}:{task.task_id}:{task.agent_id}",
                        )
                        active[active_task] = task
                        record = state.task_records[str(task.task_id)].model_copy(
                            update={
                                "status": TaskStatus.RUNNING,
                                "started_at": datetime.now(timezone.utc),
                            }
                        )
                        state = self._replace_record(state, record)

                if not active:
                    pending = [
                        record
                        for record in state.task_records.values()
                        if record.status in {TaskStatus.PENDING, TaskStatus.BLOCKED}
                    ]
                    if pending:
                        state = self._with_status(
                            state,
                            RunStatus.FAILED,
                            error="Task graph cannot make progress; dependency cycle or unresolved task.",
                        )
                        await self._publish(
                            state,
                            RunEventType.RUN_FAILED,
                            "El grafo de tareas no puede progresar.",
                        )
                        return state
                    break

                cancellation_waiter = asyncio.create_task(cancel_event.wait())
                done, _ = await asyncio.wait(
                    [*active, cancellation_waiter],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancellation_waiter in done:
                    continue
                cancellation_waiter.cancel()
                await asyncio.gather(cancellation_waiter, return_exceptions=True)
                for completed in done:
                    if completed is cancellation_waiter:
                        continue
                    task = active.pop(completed)
                    try:
                        outcome = completed.result()
                    except asyncio.CancelledError:
                        continue
                    state = await self._apply_outcome(state, task, outcome)

            failed_or_skipped = any(
                record.status in {TaskStatus.FAILED, TaskStatus.SKIPPED}
                for record in state.task_records.values()
            )
            if failed_or_skipped:
                reporting_record = next(
                    (
                        record
                        for record in state.task_records.values()
                        if record.agent_id == "evidence_reporting_analyst"
                    ),
                    None,
                )
                if (
                    reporting_record is not None
                    and reporting_record.status == TaskStatus.COMPLETED
                ):
                    state = self._with_status(
                        state,
                        RunStatus.COMPLETED_WITH_WARNINGS,
                        error=(
                            "La evaluación terminó con cobertura parcial; "
                            "consulta el informe para ver las limitaciones."
                        ),
                    )
                    await self._publish(
                        state,
                        RunEventType.RUN_COMPLETED_WITH_WARNINGS,
                        (
                            "Evaluación completada con advertencias y reporte "
                            "profesional disponible."
                        ),
                    )
                else:
                    state = self._with_status(
                        state,
                        RunStatus.FAILED,
                        error=(
                            "One or more agent tasks failed and the final "
                            "report could not be completed."
                        ),
                    )
                    await self._publish(
                        state,
                        RunEventType.RUN_FAILED,
                        "Run terminado sin poder completar el reporte final.",
                    )
            else:
                state = self._with_status(state, RunStatus.COMPLETED)
                await self._publish(
                    state,
                    RunEventType.RUN_COMPLETED,
                    "Todos los agentes completaron sus tareas.",
                )
            return state
        finally:
            for task in active:
                task.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)
            self._cancel_events.pop(state.run_id, None)

    async def cancel(self, run_id: UUID) -> RunStateV1:
        state = self.store.get_run(run_id)
        if state is None:
            raise LookupError(f"Run not found: {run_id}")
        if state.status in {
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_WITH_WARNINGS,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            return state
        state = state.model_copy(
            update={
                "status": RunStatus.CANCELLING,
                "cancellation_requested": True,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.store.save_run(state)
        cancel_event = self._cancel_events.get(run_id)
        if cancel_event is not None:
            cancel_event.set()
        await self._publish(
            state,
            RunEventType.RUN_CANCELLATION_REQUESTED,
            "Cancelación solicitada por el usuario.",
        )
        return state

    def get_run(self, run_id: UUID) -> RunStateV1 | None:
        return self.store.get_run(run_id)

    def _validate_plan(
        self,
        mission: UserMissionRequestV1,
        plan: SwarmExecutionPlanV1,
    ) -> None:
        if plan.mission_id != mission.mission_id:
            raise ValueError("Plan and mission IDs must match")
        missing_agents = plan.selected_agents - self.registry.agent_ids
        if missing_agents:
            raise LookupError(f"Missing agent executors: {sorted(missing_agents)}")
        task_ids = {task.task_id for task in plan.tasks}
        for task in plan.tasks:
            unknown = set(task.depends_on) - task_ids
            if unknown:
                raise ValueError(f"Task {task.task_id} has unknown dependencies: {unknown}")
        self._assert_acyclic(plan.tasks)

    def _assert_acyclic(self, tasks: list[SpecialistTaskV1]) -> None:
        graph = {task.task_id: set(task.depends_on) for task in tasks}
        visiting: set[UUID] = set()
        visited: set[UUID] = set()

        def visit(task_id: UUID) -> None:
            if task_id in visiting:
                raise ValueError("Task dependency graph contains a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in graph[task_id]:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in graph:
            visit(task_id)

    async def _run_task(
        self,
        run_id: UUID,
        mission: UserMissionRequestV1,
        task: SpecialistTaskV1,
        dependency_outputs: dict[str, AgentOutputEnvelopeV1],
        dependency_failures: dict[str, DependencyFailureV1],
    ) -> _TaskOutcome:
        executor = self.registry.get(task.agent_id)
        for attempt in range(1, self.max_retries + 2):
            event_type = RunEventType.AGENT_STARTED if attempt == 1 else RunEventType.AGENT_RETRYING
            await self.events.publish(
                RunEventV1(
                    run_id=run_id,
                    event_type=event_type,
                    agent_id=task.agent_id,
                    task_id=task.task_id,
                    message=(
                        f"{task.agent_id} inició la tarea."
                        if attempt == 1
                        else f"{task.agent_id} reintenta la tarea (intento {attempt})."
                    ),
                    payload={"attempt": attempt, "objective": task.objective},
                )
            )
            context = AgentExecutionContextV1(
                run_id=run_id,
                mission=mission,
                attempt=attempt,
                dependency_outputs=dependency_outputs,
                dependency_failures=dependency_failures,
            )
            try:
                output = await asyncio.wait_for(
                    executor.execute(task, context),
                    timeout=task.timeout_seconds,
                )
                self._validate_agent_output(run_id, task, output)
                return _TaskOutcome(attempts=attempt, output=output)
            except asyncio.CancelledError:
                raise
            except TimeoutError as exc:
                error_class = "TaskTimeout"
                error_message = str(exc) or f"Task timed out after {task.timeout_seconds}s"
            except Exception as exc:  # agent/tool boundary
                error_class = type(exc).__name__
                error_message = str(exc).strip() or type(exc).__name__
            if attempt > self.max_retries:
                return _TaskOutcome(
                    attempts=attempt,
                    error_class=error_class,
                    error_message=error_message,
                )
        raise AssertionError("Unreachable retry state")

    def _validate_agent_output(
        self,
        run_id: UUID,
        task: SpecialistTaskV1,
        output: AgentOutputEnvelopeV1,
    ) -> None:
        if output.run_id != run_id:
            raise ValueError("Agent output run_id does not match active run")
        if output.task_id != task.task_id:
            raise ValueError("Agent output task_id does not match assigned task")
        if output.agent_id != task.agent_id:
            raise ValueError("Agent output agent_id does not match assigned agent")

    async def _apply_outcome(
        self,
        state: RunStateV1,
        task: SpecialistTaskV1,
        outcome: _TaskOutcome,
    ) -> RunStateV1:
        completed_at = datetime.now(timezone.utc)
        current = state.task_records[str(task.task_id)]
        if outcome.succeeded:
            record = current.model_copy(
                update={
                    "status": TaskStatus.COMPLETED,
                    "attempts": outcome.attempts,
                    "completed_at": completed_at,
                    "output": outcome.output,
                    "error_class": None,
                    "error_message": None,
                }
            )
            state = self._replace_record(state, record)
            await self._publish(
                state,
                RunEventType.AGENT_COMPLETED,
                f"{task.agent_id} completó la tarea.",
                task=task,
                payload={"attempts": outcome.attempts},
            )
        else:
            record = current.model_copy(
                update={
                    "status": TaskStatus.FAILED,
                    "attempts": outcome.attempts,
                    "completed_at": completed_at,
                    "error_class": outcome.error_class or "AgentExecutionError",
                    "error_message": outcome.error_message or "Agent execution failed",
                }
            )
            state = self._replace_record(state, record)
            await self._publish(
                state,
                RunEventType.AGENT_FAILED,
                f"{task.agent_id} falló después de {outcome.attempts} intento(s).",
                task=task,
                payload={
                    "attempts": outcome.attempts,
                    "error_class": record.error_class,
                    "error_message": record.error_message,
                },
            )
        return state

    async def _skip_tasks_with_failed_dependencies(
        self,
        state: RunStateV1,
        tasks_by_id: dict[UUID, SpecialistTaskV1],
    ) -> RunStateV1:
        changed = True
        while changed:
            changed = False
            for task in tasks_by_id.values():
                record = state.task_records[str(task.task_id)]
                if record.status != TaskStatus.PENDING:
                    continue
                dependency_records = [state.task_records[str(item)] for item in task.depends_on]
                if (
                    task.dependency_policy == "all_successful"
                    and any(
                    dependency.status in {TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}
                    for dependency in dependency_records
                    )
                ):
                    skipped = record.model_copy(
                        update={
                            "status": TaskStatus.SKIPPED,
                            "completed_at": datetime.now(timezone.utc),
                            "error_class": "DependencyFailed",
                            "error_message": "A required dependency did not complete successfully.",
                        }
                    )
                    state = self._replace_record(state, skipped)
                    await self._publish(
                        state,
                        RunEventType.AGENT_SKIPPED,
                        f"{task.agent_id} no se ejecutó por una dependencia fallida.",
                        task=task,
                    )
                    changed = True
        return state

    def _runnable_tasks(
        self,
        state: RunStateV1,
        tasks: list[SpecialistTaskV1],
    ) -> list[SpecialistTaskV1]:
        runnable: list[SpecialistTaskV1] = []
        for task in tasks:
            record = state.task_records[str(task.task_id)]
            if record.status != TaskStatus.PENDING:
                continue
            dependencies = [state.task_records[str(item)] for item in task.depends_on]
            if task.dependency_policy == "all_terminal":
                ready = all(
                    item.status
                    in {
                        TaskStatus.COMPLETED,
                        TaskStatus.FAILED,
                        TaskStatus.SKIPPED,
                        TaskStatus.CANCELLED,
                    }
                    for item in dependencies
                )
            else:
                ready = all(
                    item.status == TaskStatus.COMPLETED
                    for item in dependencies
                )
            if ready:
                runnable.append(task)
        return runnable

    def _dependency_outputs(
        self,
        state: RunStateV1,
        task: SpecialistTaskV1,
    ) -> dict[str, AgentOutputEnvelopeV1]:
        return {
            str(dependency_id): output
            for dependency_id in task.depends_on
            if (output := state.task_records[str(dependency_id)].output) is not None
        }

    def _dependency_failures(
        self,
        state: RunStateV1,
        task: SpecialistTaskV1,
    ) -> dict[str, DependencyFailureV1]:
        return {
            str(dependency_id): DependencyFailureV1(
                agent_id=record.agent_id,
                status=record.status,
                error_class=record.error_class,
                error_message=record.error_message,
            )
            for dependency_id in task.depends_on
            if (
                record := state.task_records[str(dependency_id)]
            ).status
            in {
                TaskStatus.FAILED,
                TaskStatus.SKIPPED,
                TaskStatus.CANCELLED,
            }
        }

    async def _cancel_active_and_pending(
        self,
        state: RunStateV1,
        active: dict[asyncio.Task[_TaskOutcome], SpecialistTaskV1],
    ) -> RunStateV1:
        for running in active:
            running.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        now = datetime.now(timezone.utc)
        records = dict(state.task_records)
        for key, record in records.items():
            if record.status in {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.BLOCKED}:
                records[key] = record.model_copy(
                    update={"status": TaskStatus.CANCELLED, "completed_at": now}
                )
        state = state.model_copy(
            update={
                "status": RunStatus.CANCELLED,
                "cancellation_requested": True,
                "task_records": records,
                "updated_at": now,
            }
        )
        self.store.save_run(state)
        await self._publish(state, RunEventType.RUN_CANCELLED, "Run cancelado de forma segura.")
        return state

    def _replace_record(
        self,
        state: RunStateV1,
        record: TaskExecutionRecordV1,
    ) -> RunStateV1:
        records = dict(state.task_records)
        records[str(record.task_id)] = record
        updated = state.model_copy(
            update={"task_records": records, "updated_at": datetime.now(timezone.utc)}
        )
        self.store.save_run(updated)
        return updated

    def _with_status(
        self,
        state: RunStateV1,
        status: RunStatus,
        error: str | None = None,
    ) -> RunStateV1:
        updated = state.model_copy(
            update={
                "status": status,
                "error": error,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.store.save_run(updated)
        return updated

    async def _publish(
        self,
        state: RunStateV1,
        event_type: RunEventType,
        message: str,
        task: SpecialistTaskV1 | None = None,
        payload: dict[str, object] | None = None,
    ) -> RunEventV1:
        return await self.events.publish(
            RunEventV1(
                run_id=state.run_id,
                event_type=event_type,
                agent_id=task.agent_id if task else None,
                task_id=task.task_id if task else None,
                message=message,
                payload=payload or {},
            )
        )

    def _all_terminal(self, state: RunStateV1) -> bool:
        terminal = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        }
        return all(record.status in terminal for record in state.task_records.values())
