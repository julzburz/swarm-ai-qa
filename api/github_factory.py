from __future__ import annotations

from fastapi import FastAPI

from executors import build_github_registry

from .app import create_app


def create_github_app() -> FastAPI:
    """Production-shaped factory with the first real GitHub read-only executors."""

    return create_app(registry=build_github_registry())
