from __future__ import annotations

import os

from adapters.github import GitHubReadClient, GitHubRestClient
from orchestrator import AgentRegistry
from workers.accessibility import AccessibilityWorker, PlaywrightAxeWorker
from workers.browser import BrowserWorker, PlaywrightBrowserWorker

from .accessibility import AccessibilityExecutor
from .browser import BrowserAutomationExecutor
from .reporting import EvidenceReportingExecutor
from .repository import RepositoryAnalystExecutor
from .test_architect import TestArchitectExecutor


def build_github_registry(client: GitHubReadClient | None = None) -> AgentRegistry:
    github = client or GitHubRestClient.from_env()
    registry = AgentRegistry()
    registry.register(RepositoryAnalystExecutor(github))
    registry.register(TestArchitectExecutor())
    registry.register(EvidenceReportingExecutor())
    return registry


def build_automation_registry(
    github_client: GitHubReadClient | None = None,
    browser_worker: BrowserWorker | None = None,
    accessibility_worker: AccessibilityWorker | None = None,
) -> AgentRegistry:
    registry = build_github_registry(github_client)
    worker = browser_worker or PlaywrightBrowserWorker(
        os.getenv("SWARM_ARTIFACT_ROOT", ".data/artifacts")
    )
    registry.register(BrowserAutomationExecutor(worker))
    axe_worker = accessibility_worker or PlaywrightAxeWorker(
        os.getenv("SWARM_ARTIFACT_ROOT", ".data/artifacts")
    )
    registry.register(AccessibilityExecutor(axe_worker))
    return registry
