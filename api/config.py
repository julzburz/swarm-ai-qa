from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Small environment-backed settings surface for the first API slice."""

    sqlite_path: Path = Path(".data/swarm-ai-qa.db")
    title: str = "Swarm AI QA Control Plane"
    version: str = "0.1.0"

    @classmethod
    def from_env(cls) -> "ApiSettings":
        sqlite_path = os.getenv("SWARM_SQLITE_PATH", ".data/swarm-ai-qa.db").strip()
        if not sqlite_path:
            raise ValueError("SWARM_SQLITE_PATH cannot be empty")
        return cls(sqlite_path=Path(sqlite_path))
