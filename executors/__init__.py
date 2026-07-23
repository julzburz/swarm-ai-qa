"""Concrete, schema-validating agent executors."""

from .accessibility import AccessibilityExecutor
from .api import ApiTestExecutor
from .browser import BrowserAutomationExecutor
from .factory import build_automation_registry, build_github_registry
from .performance import PerformanceExecutor
from .reporting import EvidenceReportingExecutor
from .release import ReleaseManagerExecutor
from .repository import RepositoryAnalystExecutor
from .security import SecurityExecutor
from .test_architect import TestArchitectExecutor

__all__ = [
    "AccessibilityExecutor",
    "ApiTestExecutor",
    "EvidenceReportingExecutor",
    "BrowserAutomationExecutor",
    "PerformanceExecutor",
    "RepositoryAnalystExecutor",
    "ReleaseManagerExecutor",
    "SecurityExecutor",
    "TestArchitectExecutor",
    "build_github_registry",
    "build_automation_registry",
]
