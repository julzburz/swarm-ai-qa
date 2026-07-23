from __future__ import annotations

from fastapi import FastAPI

from executors import build_automation_registry

from .app import create_app


def create_automation_app() -> FastAPI:
    """Factory with GitHub read-only and Playwright navigation executors."""

    return create_app(registry=build_automation_registry())
