from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, create_engine, insert, select, text, update

from database.config import DatabaseSettings
from database.models import metadata, run_events, run_tasks, runs

from .models import RunEventV1, RunStateV1


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


class NeonRunStore:
    """RunStore compartido respaldado por Neon/PostgreSQL."""

    def __init__(
        self,
        settings: DatabaseSettings | None = None,
        *,
        engine: Engine | None = None,
        create_schema: bool = False,
    ) -> None:
        if engine is None:
            if settings is None:
                raise ValueError("settings or engine is required")
            settings.validate_neon_topology()
            engine = create_engine(
                settings.sqlalchemy_url,
                pool_pre_ping=True,
                pool_size=settings.pool_size,
                max_overflow=settings.max_overflow,
                pool_recycle=settings.pool_recycle_seconds,
                future=True,
            )
        self.engine = engine
        if create_schema:
            metadata.create_all(self.engine)

    @classmethod
    def from_env(cls) -> "NeonRunStore":
        return cls(DatabaseSettings.from_env())

    def healthcheck(self) -> bool:
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1

    def schema_is_ready(self) -> bool:
        from sqlalchemy import inspect

        inspector = inspect(self.engine)
        required = {"runs", "run_tasks", "run_events"}
        return required.issubset(set(inspector.get_table_names()))

    def save_run(self, state: RunStateV1) -> None:
        state_json = state.model_dump(mode="json")
        run_values = {
            "run_id": state.run_id,
            "mission_id": state.mission.mission_id,
            "status": state.status.value,
            "state_json": state_json,
            "error": state.error,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
        }
        with self.engine.begin() as connection:
            result = connection.execute(
                update(runs).where(runs.c.run_id == state.run_id).values(**run_values)
            )
            if result.rowcount == 0:
                connection.execute(insert(runs).values(**run_values))

            for record in state.task_records.values():
                task_values = {
                    "task_id": record.task_id,
                    "run_id": state.run_id,
                    "agent_id": record.agent_id,
                    "status": record.status.value,
                    "attempts": record.attempts,
                    "record_json": record.model_dump(mode="json"),
                    "started_at": record.started_at,
                    "completed_at": record.completed_at,
                    "updated_at": state.updated_at,
                }
                task_result = connection.execute(
                    update(run_tasks)
                    .where(run_tasks.c.task_id == record.task_id)
                    .values(**task_values)
                )
                if task_result.rowcount == 0:
                    connection.execute(insert(run_tasks).values(**task_values))

    def get_run(self, run_id: UUID) -> RunStateV1 | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(runs.c.state_json).where(runs.c.run_id == run_id)
            ).first()
        if row is None:
            return None
        return RunStateV1.model_validate(_json_value(row.state_json))

    def list_runs(self, limit: int = 20, offset: int = 0) -> list[RunStateV1]:
        statement = (
            select(runs.c.state_json)
            .order_by(runs.c.updated_at.desc(), runs.c.run_id.desc())
            .limit(limit)
            .offset(offset)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).all()
        return [
            RunStateV1.model_validate(_json_value(row.state_json))
            for row in rows
        ]

    def append_event(self, event: RunEventV1) -> RunEventV1:
        event_without_sequence = event.model_copy(update={"sequence": None})
        with self.engine.begin() as connection:
            sequence = connection.execute(
                insert(run_events)
                .values(
                    event_id=event.event_id,
                    run_id=event.run_id,
                    event_type=event.event_type.value,
                    agent_id=event.agent_id,
                    task_id=event.task_id,
                    event_json=event_without_sequence.model_dump(mode="json"),
                    occurred_at=event.occurred_at,
                )
                .returning(run_events.c.sequence)
            ).scalar_one()
            stored = event.model_copy(update={"sequence": int(sequence)})
            connection.execute(
                update(run_events)
                .where(run_events.c.sequence == sequence)
                .values(event_json=stored.model_dump(mode="json"))
            )
        return stored

    def list_events(self, run_id: UUID, after_sequence: int = 0) -> list[RunEventV1]:
        statement = (
            select(run_events.c.event_json)
            .where(
                run_events.c.run_id == run_id,
                run_events.c.sequence > after_sequence,
            )
            .order_by(run_events.c.sequence.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).all()
        return [RunEventV1.model_validate(_json_value(row.event_json)) for row in rows]

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> "NeonRunStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
