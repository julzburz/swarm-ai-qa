from __future__ import annotations

import os

from adapters.github import GitHubReadClient, GitHubRestClient
from orchestrator import AgentRegistry
from workers.accessibility import AccessibilityWorker, PlaywrightAxeWorker
from workers.api import ApiWorker, SafeHttpApiWorker
from workers.browser import BrowserWorker, PlaywrightBrowserWorker
from workers.performance import PerformanceWorker, PlaywrightPerformanceWorker
from workers.security import PassiveHttpSecurityWorker, SecurityWorker

from .accessibility import AccessibilityExecutor
from .api import ApiTestExecutor
from .browser import BrowserAutomationExecutor
from .performance import PerformanceExecutor
from .reporting import EvidenceReportingExecutor
from .repository import RepositoryAnalystExecutor
from .security import SecurityExecutor
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
    security_worker: SecurityWorker | None = None,
    performance_worker: PerformanceWorker | None = None,
    api_worker: ApiWorker | None = None,
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
    passive_security_worker = security_worker or PassiveHttpSecurityWorker(
        os.getenv("SWARM_ARTIFACT_ROOT", ".data/artifacts")
    )
    registry.register(SecurityExecutor(passive_security_worker))
    perf_worker = performance_worker or PlaywrightPerformanceWorker(
        os.getenv("SWARM_ARTIFACT_ROOT", ".data/artifacts")
    )
    registry.register(PerformanceExecutor(perf_worker))
    safe_api_worker = api_worker or SafeHttpApiWorker(
        os.getenv("SWARM_ARTIFACT_ROOT", ".data/artifacts")
    )
    registry.register(ApiTestExecutor(safe_api_worker))
    return registry
