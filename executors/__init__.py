"""Concrete, schema-validating agent executors."""

from .accessibility import AccessibilityExecutor
from .browser import BrowserAutomationExecutor
from .factory import build_automation_registry, build_github_registry
from .reporting import EvidenceReportingExecutor
from .repository import RepositoryAnalystExecutor
from .security import SecurityExecutor
from .test_architect import TestArchitectExecutor

__all__ = [
    "AccessibilityExecutor",
    "EvidenceReportingExecutor",
    "BrowserAutomationExecutor",
    "RepositoryAnalystExecutor",
    "SecurityExecutor",
    "TestArchitectExecutor",
    "build_github_registry",
    "build_automation_registry",
]
