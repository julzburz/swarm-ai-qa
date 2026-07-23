from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Security, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from adapters.github import GitHubApiError
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
from schemas.common import QualityDomain, Severity
from schemas.mission import UserMissionRequestV1

from .config import ApiSettings
from .controller import (
    MissingExecutorsError,
    PlanPreviewExpiredError,
    RunController,
)
from .schemas import (
    ArtifactListResponseV1,
    CreateRunRequestV1,
    FindingListResponseV1,
    HealthResponseV1,
    PlanPreviewResponseV1,
    RunAcceptedResponseV1,
    RunSummaryV1,
)
from .results import (
    artifact_integrity_matches,
    artifacts_response,
    find_artifact_record,
    findings_response,
    resolve_local_artifact,
)


TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.COMPLETED_WITH_WARNINGS,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}


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
    bearer = HTTPBearer(auto_error=False)

    async def require_api_key(
        credentials: HTTPAuthorizationCredentials | None = Security(bearer),
    ) -> None:
        if settings.api_key is None:
            return
        supplied = credentials.credentials if credentials is not None else ""
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not secrets.compare_digest(supplied, settings.api_key)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid bearer API key required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    protected = [Depends(require_api_key)]

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
            authentication="bearer" if settings.api_key else "disabled",
        )

    @app.post(
        "/v1/plans/preview",
        response_model=PlanPreviewResponseV1,
        tags=["runs"],
        dependencies=protected,
    )
    async def preview_plan(mission: UserMissionRequestV1) -> PlanPreviewResponseV1:
        try:
            preview = await controller.preview(mission)
        except GitHubApiError as exc:
            status_code = (
                exc.status_code
                if exc.status_code in {401, 403, 404, 429}
                else status.HTTP_502_BAD_GATEWAY
            )
            raise HTTPException(
                status_code=status_code,
                detail={
                    "code": "repository_reconnaissance_failed",
                    "message": str(exc),
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "reconnaissance_failed",
                    "message": str(exc),
                },
            ) from exc
        plan = preview.plan
        missing = controller.missing_executors(plan)
        return PlanPreviewResponseV1(
            mission=preview.mission,
            plan=plan,
            reconnaissance=preview.reconnaissance,
            runtime_reconnaissance=preview.runtime_reconnaissance,
            planning_basis=preview.planning_basis,
            missing_executors=missing,
            executable=not missing,
        )

    @app.post(
        "/v1/runs",
        response_model=RunAcceptedResponseV1,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["runs"],
        dependencies=protected,
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
            plan = controller.approved_plan(
                request.mission,
                request.approved_plan_id,
            )
        except PlanPreviewExpiredError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "plan_preview_expired",
                    "message": (
                        "El reconocimiento aprobado ya no está disponible. "
                        "Genera nuevamente el plan antes de ejecutar."
                    ),
                },
            ) from exc
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
        controller.discard_preview(request.mission.mission_id)
        base = f"/v1/runs/{run_id}"
        return RunAcceptedResponseV1(
            run_id=run_id,
            mission_id=request.mission.mission_id,
            plan=plan,
            state_url=base,
            events_url=f"{base}/events",
            event_stream_url=f"{base}/events/stream",
        )

    @app.get(
        "/v1/runs",
        response_model=list[RunSummaryV1],
        tags=["runs"],
        dependencies=protected,
    )
    async def list_runs(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[RunSummaryV1]:
        return [
            _summarize_run(state)
            for state in run_store.list_runs(limit=limit, offset=offset)
        ]

    @app.get(
        "/v1/runs/{run_id}",
        response_model=RunStateV1,
        tags=["runs"],
        dependencies=protected,
    )
    async def get_run(run_id: UUID) -> RunStateV1:
        state = orchestrator.get_run(run_id)
        if state is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        return state

    @app.get(
        "/v1/runs/{run_id}/findings",
        response_model=FindingListResponseV1,
        tags=["results"],
        dependencies=protected,
    )
    async def list_findings(
        run_id: UUID,
        domain: QualityDomain | None = None,
        severity: Severity | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> FindingListResponseV1:
        state = _require_run(run_store, run_id)
        return findings_response(
            state,
            domain=domain,
            severity=severity,
            limit=limit,
            offset=offset,
        )

    @app.get(
        "/v1/runs/{run_id}/artifacts",
        response_model=ArtifactListResponseV1,
        tags=["results"],
        dependencies=protected,
    )
    async def list_artifacts(run_id: UUID) -> ArtifactListResponseV1:
        state = _require_run(run_store, run_id)
        return artifacts_response(state, settings.artifact_root)

    @app.get(
        "/v1/runs/{run_id}/artifacts/{artifact_id}",
        response_class=FileResponse,
        tags=["results"],
        dependencies=protected,
    )
    async def download_artifact(
        run_id: UUID,
        artifact_id: Annotated[
            str,
            Path(pattern=r"^[a-f0-9]{64}$"),
        ],
    ) -> FileResponse:
        state = _require_run(run_store, run_id)
        record = find_artifact_record(state, artifact_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact not found for this run",
            )
        artifact_path = resolve_local_artifact(
            run_id,
            record,
            settings.artifact_root,
        )
        if artifact_path is None or not artifact_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Artifact is not materialized on this control plane",
            )
        integrity_matches = await asyncio.to_thread(
            artifact_integrity_matches,
            artifact_path,
            record.ref.sha256,
        )
        if not integrity_matches:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Artifact integrity verification failed",
            )
        return FileResponse(
            artifact_path,
            media_type=record.ref.media_type,
            filename=artifact_path.name,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post(
        "/v1/runs/{run_id}/cancel",
        response_model=RunStateV1,
        tags=["runs"],
        dependencies=protected,
    )
    async def cancel_run(run_id: UUID) -> RunStateV1:
        try:
            return await orchestrator.cancel(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from exc

    @app.get(
        "/v1/runs/{run_id}/events",
        response_model=list[RunEventV1],
        tags=["events"],
        dependencies=protected,
    )
    async def list_events(
        run_id: UUID,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
    ) -> list[RunEventV1]:
        _require_run(run_store, run_id)
        return run_store.list_events(run_id, after_sequence)

    @app.get(
        "/v1/runs/{run_id}/events/stream",
        tags=["events"],
        dependencies=protected,
    )
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


def _summarize_run(state: RunStateV1) -> RunSummaryV1:
    has_repository = state.mission.repository_target is not None
    has_runtime = state.mission.runtime_target is not None
    source = (
        "combined"
        if has_repository and has_runtime
        else "repository"
        if has_repository
        else "runtime"
    )
    return RunSummaryV1(
        run_id=state.run_id,
        mission_id=state.mission.mission_id,
        objective=state.mission.objective,
        mode=state.mission.mode,
        source=source,
        status=state.status,
        agent_count=len(state.task_records),
        completed_agents=sum(
            record.status.value == "completed"
            for record in state.task_records.values()
        ),
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


def _format_sse(event: RunEventV1) -> str:
    event_name = event.event_type.value
    event_id = str(event.sequence or "")
    return f"id: {event_id}\nevent: {event_name}\ndata: {event.model_dump_json()}\n\n"
