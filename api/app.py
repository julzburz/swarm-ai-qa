from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from orchestrator import (
    AgentRegistry,
    EventStream,
    NeonRunStore,
    RuleBasedQaDirector,
    SQLiteRunStore,
    SwarmOrchestrator,
)
from database.config import DatabaseSettings
from orchestrator.models import RunEventV1, RunStateV1, RunStatus
from orchestrator.store import RunStore
from schemas.mission import UserMissionRequestV1

from .config import ApiSettings
from .controller import MissingExecutorsError, RunController
from .schemas import (
    CreateRunRequestV1,
    HealthResponseV1,
    PlanPreviewResponseV1,
    RunAcceptedResponseV1,
)


TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


def create_app(
    *,
    settings: ApiSettings | None = None,
    store: RunStore | None = None,
    registry: AgentRegistry | None = None,
) -> FastAPI:
    settings = settings or ApiSettings.from_env()
    owns_store = store is None
    run_store = store or _create_run_store(settings)
    storage_backend = (
        "neon" if isinstance(run_store, NeonRunStore) else "sqlite"
    )
    agent_registry = registry or AgentRegistry()
    events = EventStream(run_store)
    orchestrator = SwarmOrchestrator(agent_registry, run_store, events)
    director = RuleBasedQaDirector()
    controller = RunController(orchestrator, agent_registry, director)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            if isinstance(run_store, NeonRunStore):
                healthy = await asyncio.to_thread(run_store.healthcheck)
                schema_ready = await asyncio.to_thread(
                    run_store.schema_is_ready
                )
                if not healthy:
                    raise RuntimeError("Neon healthcheck failed")
                if not schema_ready:
                    raise RuntimeError(
                        "Neon schema is not ready; run alembic upgrade head"
                    )
            yield
        finally:
            await controller.shutdown()
            if owns_store:
                run_store.close()

    app = FastAPI(
        title=settings.title,
        version=settings.version,
        description=(
            "Control plane read-only para planificar y observar ejecuciones de QA. "
            "No genera ni modifica codigo del repositorio evaluado."
        ),
        lifespan=lifespan,
    )
    app.state.controller = controller
    app.state.orchestrator = orchestrator
    app.state.run_store = run_store
    app.state.event_stream = events
    app.state.storage_backend = storage_backend

    @app.get("/healthz", response_model=HealthResponseV1, tags=["system"])
    async def health() -> HealthResponseV1:
        return HealthResponseV1(
            version=settings.version,
            storage=storage_backend,
        )

    @app.post(
        "/v1/plans/preview",
        response_model=PlanPreviewResponseV1,
        tags=["runs"],
    )
    async def preview_plan(mission: UserMissionRequestV1) -> PlanPreviewResponseV1:
        plan = controller.plan(mission)
        missing = controller.missing_executors(plan)
        return PlanPreviewResponseV1(
            mission=mission,
            plan=plan,
            missing_executors=missing,
            executable=not missing,
        )

    @app.post(
        "/v1/runs",
        response_model=RunAcceptedResponseV1,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["runs"],
    )
    async def create_run(request: CreateRunRequestV1) -> RunAcceptedResponseV1:
        plan = controller.plan(request.mission)
        if plan.requires_approval and not request.approved:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "approval_required",
                    "message": "Preview the plan and resubmit with approved=true.",
                    "plan": plan.model_dump(mode="json"),
                },
            )
        try:
            run_id = await controller.start(request.mission, plan)
        except MissingExecutorsError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "missing_executors",
                    "message": "The selected agents are not connected to executors.",
                    "agent_ids": exc.agent_ids,
                },
            ) from exc
        base = f"/v1/runs/{run_id}"
        return RunAcceptedResponseV1(
            run_id=run_id,
            mission_id=request.mission.mission_id,
            plan=plan,
            state_url=base,
            events_url=f"{base}/events",
            event_stream_url=f"{base}/events/stream",
        )

    @app.get("/v1/runs/{run_id}", response_model=RunStateV1, tags=["runs"])
    async def get_run(run_id: UUID) -> RunStateV1:
        state = orchestrator.get_run(run_id)
        if state is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        return state

    @app.post("/v1/runs/{run_id}/cancel", response_model=RunStateV1, tags=["runs"])
    async def cancel_run(run_id: UUID) -> RunStateV1:
        try:
            return await orchestrator.cancel(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from exc

    @app.get(
        "/v1/runs/{run_id}/events",
        response_model=list[RunEventV1],
        tags=["events"],
    )
    async def list_events(
        run_id: UUID,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
    ) -> list[RunEventV1]:
        _require_run(run_store, run_id)
        return run_store.list_events(run_id, after_sequence)

    @app.get("/v1/runs/{run_id}/events/stream", tags=["events"])
    async def stream_events(
        request: Request,
        run_id: UUID,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
    ) -> StreamingResponse:
        initial_state = _require_run(run_store, run_id)

        async def event_source() -> AsyncIterator[str]:
            if initial_state.status in TERMINAL_STATUSES:
                for event in run_store.list_events(run_id, after_sequence):
                    yield _format_sse(event)
                return

            async for event in events.subscribe(run_id, after_sequence):
                if await request.is_disconnected():
                    return
                yield _format_sse(event)

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _create_run_store(settings: ApiSettings) -> RunStore:
    if settings.storage_backend == "neon":
        database_settings = DatabaseSettings.from_env(
            env_file=None,
            require_direct=False,
        )
        return NeonRunStore(database_settings)
    return SQLiteRunStore(settings.sqlite_path)


def _require_run(store: RunStore, run_id: UUID) -> RunStateV1:
    state = store.get_run(run_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return state


def _format_sse(event: RunEventV1) -> str:
    event_name = event.event_type.value
    event_id = str(event.sequence or "")
    return f"id: {event_id}\nevent: {event_name}\ndata: {event.model_dump_json()}\n\n"
