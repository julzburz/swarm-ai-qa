"""Concrete, schema-validating agent executors."""

from .browser import BrowserAutomationExecutor
from .factory import build_automation_registry, build_github_registry
from .reporting import EvidenceReportingExecutor
from .repository import RepositoryAnalystExecutor
from .test_architect import TestArchitectExecutor

__all__ = [
    "EvidenceReportingExecutor",
    "BrowserAutomationExecutor",
    "RepositoryAnalystExecutor",
    "TestArchitectExecutor",
    "build_github_registry",
    "build_automation_registry",
]
