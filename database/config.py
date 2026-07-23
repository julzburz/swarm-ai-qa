from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv


def _sqlalchemy_psycopg_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    raise ValueError("Database URL must use postgres:// or postgresql://")


def _host(url: str) -> str:
    normalized = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return urlsplit(normalized).hostname or ""


@dataclass(frozen=True, repr=False)
class DatabaseSettings:
    """URLs separadas para tráfico de aplicación y migraciones."""

    database_url: str
    database_direct_url: str
    pool_size: int = 5
    max_overflow: int = 10
    pool_recycle_seconds: int = 300

    def __post_init__(self) -> None:
        _sqlalchemy_psycopg_url(self.database_url)
        _sqlalchemy_psycopg_url(self.database_direct_url)
        if self.pool_size <= 0:
            raise ValueError("pool_size must be positive")
        if self.max_overflow < 0:
            raise ValueError("max_overflow cannot be negative")
        if self.pool_recycle_seconds <= 0:
            raise ValueError("pool_recycle_seconds must be positive")

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> "DatabaseSettings":
        if env_file is not None:
            load_dotenv(dotenv_path=env_file, override=False)
        database_url = os.getenv("DATABASE_URL", "").strip()
        direct_url = os.getenv("DATABASE_DIRECT_URL", "").strip()
        if not database_url:
            raise RuntimeError("DATABASE_URL is required")
        if not direct_url:
            raise RuntimeError("DATABASE_DIRECT_URL is required for migrations")
        return cls(
            database_url=database_url,
            database_direct_url=direct_url,
            pool_size=int(os.getenv("DATABASE_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("DATABASE_MAX_OVERFLOW", "10")),
            pool_recycle_seconds=int(os.getenv("DATABASE_POOL_RECYCLE_SECONDS", "300")),
        )

    @property
    def sqlalchemy_url(self) -> str:
        return _sqlalchemy_psycopg_url(self.database_url)

    @property
    def sqlalchemy_direct_url(self) -> str:
        return _sqlalchemy_psycopg_url(self.database_direct_url)

    @property
    def is_neon(self) -> bool:
        return _host(self.database_url).endswith(".neon.tech")

    @property
    def uses_neon_pooler(self) -> bool:
        return "-pooler." in _host(self.database_url)

    @property
    def direct_url_uses_pooler(self) -> bool:
        return "-pooler." in _host(self.database_direct_url)

    def validate_neon_topology(self) -> None:
        if not self.is_neon:
            return
        if not self.uses_neon_pooler:
            raise ValueError("DATABASE_URL must use the Neon pooled hostname (-pooler)")
        if self.direct_url_uses_pooler:
            raise ValueError("DATABASE_DIRECT_URL must use the direct Neon hostname")
