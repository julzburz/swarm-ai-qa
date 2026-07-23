from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import UUID

from .models import RunEventV1, RunStateV1


class RunStore(Protocol):
    def save_run(self, state: RunStateV1) -> None: ...

    def get_run(self, run_id: UUID) -> RunStateV1 | None: ...

    def list_runs(self, limit: int = 20, offset: int = 0) -> list[RunStateV1]: ...

    def append_event(self, event: RunEventV1) -> RunEventV1: ...

    def list_events(self, run_id: UUID, after_sequence: int = 0) -> list[RunEventV1]: ...

    def close(self) -> None: ...


class SQLiteRunStore:
    """Checkpoint store pequeño y durable para el hackathon."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_events_run_sequence "
                "ON run_events(run_id, sequence)"
            )

    def save_run(self, state: RunStateV1) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO runs(run_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (str(state.run_id), state.model_dump_json(), state.updated_at.isoformat()),
            )

    def get_run(self, run_id: UUID) -> RunStateV1 | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT state_json FROM runs WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        return RunStateV1.model_validate_json(row[0]) if row else None

    def list_runs(self, limit: int = 20, offset: int = 0) -> list[RunStateV1]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT state_json FROM runs
                ORDER BY updated_at DESC, run_id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [RunStateV1.model_validate_json(row[0]) for row in rows]

    def append_event(self, event: RunEventV1) -> RunEventV1:
        event_without_sequence = event.model_copy(update={"sequence": None})
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT INTO run_events(run_id, event_json, occurred_at) VALUES (?, ?, ?)",
                (
                    str(event.run_id),
                    event_without_sequence.model_dump_json(),
                    event.occurred_at.isoformat(),
                ),
            )
            sequence = int(cursor.lastrowid)
        stored = event.model_copy(update={"sequence": sequence})
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE run_events SET event_json = ? WHERE sequence = ?",
                (stored.model_dump_json(), sequence),
            )
        return stored

    def list_events(self, run_id: UUID, after_sequence: int = 0) -> list[RunEventV1]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_json FROM run_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (str(run_id), after_sequence),
            ).fetchall()
        return [RunEventV1.model_validate_json(row[0]) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SQLiteRunStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
