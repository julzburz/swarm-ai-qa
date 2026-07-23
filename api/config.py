from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Small environment-backed settings surface for the first API slice."""

    sqlite_path: Path = Path(".data/swarm-ai-qa.db")
    artifact_root: Path = Path(".data/artifacts")
    storage_backend: Literal["sqlite", "neon"] = "sqlite"
    api_key: str | None = field(default=None, repr=False)
    title: str = "Swarm AI QA Control Plane"
    version: str = "0.11.0"

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = ".env",
    ) -> "ApiSettings":
        if env_file is not None:
            load_dotenv(dotenv_path=env_file, override=False)
        sqlite_path = os.getenv("SWARM_SQLITE_PATH", ".data/swarm-ai-qa.db").strip()
        if not sqlite_path:
            raise ValueError("SWARM_SQLITE_PATH cannot be empty")
        artifact_root = os.getenv(
            "SWARM_ARTIFACT_ROOT",
            ".data/artifacts",
        ).strip()
        if not artifact_root:
            raise ValueError("SWARM_ARTIFACT_ROOT cannot be empty")
        requested = os.getenv("SWARM_STORAGE_BACKEND", "auto").strip().lower()
        if requested not in {"auto", "sqlite", "neon"}:
            raise ValueError(
                "SWARM_STORAGE_BACKEND must be auto, sqlite or neon"
            )
        database_configured = bool(os.getenv("DATABASE_URL", "").strip())
        storage_backend = (
            "neon"
            if requested == "neon" or requested == "auto" and database_configured
            else "sqlite"
        )
        if requested == "neon" and not database_configured:
            raise RuntimeError(
                "SWARM_STORAGE_BACKEND=neon requires DATABASE_URL"
            )
        api_key = os.getenv("SWARM_API_KEY", "").strip() or None
        if api_key is not None and len(api_key) < 32:
            raise ValueError("SWARM_API_KEY must contain at least 32 characters")
        return cls(
            sqlite_path=Path(sqlite_path),
            artifact_root=Path(artifact_root),
            storage_backend=storage_backend,
            api_key=api_key,
        )
