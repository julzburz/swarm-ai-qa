from __future__ import annotations

import asyncio
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import uvicorn
from fastapi.testclient import TestClient

from api.app import create_app
from demo_web.app import app as demo_app
from executors import build_automation_registry
from orchestrator import SQLiteRunStore
from schemas.common import Environment, MissionMode, QualityDomain, RuntimeTargetV1
from schemas.mission import UserMissionRequestV1
from workers.browser import (
    BrowserJourneyCaptureV1,
    BrowserWorkerRequestV1,
    BrowserWorkerResultV1,
    PlaywrightBrowserWorker,
)
from workers.browser.playwright_worker import url_is_allowed
from workers.browser.playwright_worker import (
    ensure_safe_runtime_destination,
    resource_url_is_allowed,
)
from tests.test_github_slice import (
    FixtureGitHubClient,
    fixture_inspection,
    monorepo_inspection,
    repository_target,
)


class BrowserPolicyTests(unittest.TestCase):
    def test_origin_and_path_policy(self) -> None:
        base = "http://127.0.0.1:8010"
        self.assertTrue(url_is_allowed(f"{base}/healthy", base, ["/healthy"], []))
        self.assertTrue(url_is_allowed(f"{base}/healthy/details", base, ["/healthy"], []))
        self.assertFalse(url_is_allowed("https://example.com/healthy", base, ["/"], []))
        self.assertFalse(url_is_allowed(f"{base}/admin", base, ["/"], ["/admin"]))
        self.assertFalse(url_is_allowed(f"{base}/health", base, ["/healthy"], []))

    def test_subresources_use_a_separate_same_origin_policy(self) -> None:
        base = "https://shop.example.com"
        self.assertTrue(
            resource_url_is_allowed(
                f"{base}/assets/application.js",
                base,
                ["/admin"],
            )
        )
        self.assertFalse(
            resource_url_is_allowed(
                "https://cdn.example.com/application.js",
                base,
                [],
            )
        )


class BrowserDestinationSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_rejects_metadata_address_without_launching_browser(self) -> None:
        with self.assertRaises(ValueError):
            await ensure_safe_runtime_destination(
                "http://169.254.169.254/latest/meta-data"
            )

    async def test_worker_rejects_hostname_that_resolves_to_private_ip(self) -> None:
        private_resolution = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("10.20.30.40", 443),
            )
        ]
        with patch(
            "workers.browser.playwright_worker.socket.getaddrinfo",
            return_value=private_resolution,
        ), self.assertRaises(ValueError):
            await ensure_safe_runtime_destination("https://qa-target.example")


class BrowserWorkerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _free_port()
        config = uvicorn.Config(
            demo_app,
            host="127.0.0.1",
            port=cls.port,
            log_level="error",
        )
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.02)
        raise RuntimeError("Demo server did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_real_playwright_captures_routes_errors_and_policy_blocks(self) -> None:
        worker = PlaywrightBrowserWorker(Path(self.temp_dir.name) / "artifacts")
        result = await worker.run(
            BrowserWorkerRequestV1(
                run_id=uuid4(),
                task_id=uuid4(),
                base_url=f"http://127.0.0.1:{self.port}",
                allowed_paths=["/healthy", "/broken", "/outbound"],
                allow_private_network=True,
                max_requests=30,
                timeout_seconds=10,
            )
        )

        by_path = {journey.path: journey for journey in result.journeys}
        self.assertEqual(by_path["/healthy"].status, "passed")
        self.assertEqual(by_path["/broken"].status, "failed")
        self.assertTrue(by_path["/broken"].page_errors)
        self.assertTrue(any("example.com/tracker.png" in url for url in result.blocked_requests))
        self.assertTrue(Path(result.trace_path).is_file())
        self.assertTrue(
            all(Path(journey.screenshot_path).is_file() for journey in result.journeys)
        )
        self.assertGreater(result.request_count, 0)


class FixtureBrowserWorker:
    def __init__(self, artifact_dir: Path, *, status: str = "passed") -> None:
        self.artifact_dir = artifact_dir
        self.status = status
        self.requests: list[BrowserWorkerRequestV1] = []

    async def run(self, request: BrowserWorkerRequestV1) -> BrowserWorkerResultV1:
        self.requests.append(request)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        screenshot = self.artifact_dir / "fixture.png"
        trace = self.artifact_dir / "fixture.zip"
        screenshot.write_bytes(b"fixture screenshot")
        trace.write_bytes(b"fixture trace")
        return BrowserWorkerResultV1(
            journeys=[
                BrowserJourneyCaptureV1(
                    name=f"Navigate {path}",
                    path=path,
                    final_url=str(request.base_url).rstrip("/") + path,
                    status=self.status,
                    http_status=200,
                    title="Healthy checkout",
                    duration_ms=10,
                    screenshot_path=str(screenshot),
                )
                for path in request.allowed_paths
            ],
            trace_path=str(trace),
            request_count=len(request.allowed_paths),
            playwright_version="fixture",
            browser_version="fixture",
        )


class BrowserApiSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.store = SQLiteRunStore(root / "browser-api.db")
        self.worker = FixtureBrowserWorker(root / "artifacts")

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_runtime_functional_mission_completes_and_reports_browser_evidence(self) -> None:
        mission = UserMissionRequestV1(
            objective="Verify the healthy checkout route",
            mode=MissionMode.TARGETED_EXAMINATION,
            runtime_target=RuntimeTargetV1(
                base_url="https://staging.example.com",
                environment=Environment.STAGING,
                allowed_paths=["/healthy"],
            ),
            selected_domains={QualityDomain.FUNCTIONAL},
        )
        app = create_app(
            store=self.store,
            registry=build_automation_registry(browser_worker=self.worker),
        )
        with TestClient(app) as client:
            preview = client.post("/v1/plans/preview", json=mission.model_dump(mode="json"))
            self.assertTrue(preview.json()["executable"])
            accepted = client.post(
                "/v1/runs",
                json={"mission": mission.model_dump(mode="json"), "approved": True},
            )
            state = _wait_for_terminal(client, accepted.json()["run_id"])

        self.assertEqual(state["status"], "completed")
        outputs = {
            record["agent_id"]: record["output"]
            for record in state["task_records"].values()
        }
        browser = outputs["browser_automation_engineer"]
        report = outputs["evidence_reporting_analyst"]
        self.assertEqual(browser["output_schema"], "BrowserAgentOutputV1")
        self.assertEqual(browser["output"]["journeys"][0]["status"], "passed")
        self.assertTrue(browser["evidence_refs"])
        self.assertEqual(report["output_schema"], "EvidenceReportingOutputV1")
        self.assertIn("Playwright executed 1", report["output"]["report"]["execution_summary"])
        self.assertEqual(self.worker.requests[0].allowed_paths, ["/healthy"])

    def test_combined_mission_correlates_repository_and_runtime_evidence(self) -> None:
        github = FixtureGitHubClient(monorepo_inspection())
        failing_worker = FixtureBrowserWorker(
            Path(self.temp_dir.name) / "combined-artifacts",
            status="failed",
        )
        mission = UserMissionRequestV1(
            objective="Correlate the checkout change with its production journey",
            mode=MissionMode.TARGETED_EXAMINATION,
            repository_target=repository_target(),
            pull_request_number=8,
            runtime_target=RuntimeTargetV1(
                base_url="https://staging.example.com",
                environment=Environment.STAGING,
                allowed_paths=["/"],
            ),
            selected_domains={QualityDomain.FUNCTIONAL},
        )
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                github_client=github,
                browser_worker=failing_worker,
            ),
        )
        with TestClient(app) as client:
            accepted = client.post(
                "/v1/runs",
                json={"mission": mission.model_dump(mode="json"), "approved": True},
            )
            state = _wait_for_terminal(client, accepted.json()["run_id"])

        self.assertEqual(state["status"], "completed")
        outputs = {
            record["agent_id"]: record["output"]
            for record in state["task_records"].values()
        }
        report = outputs["evidence_reporting_analyst"]["output"]["report"]
        source_schemas = outputs["evidence_reporting_analyst"]["output"][
            "source_output_schemas"
        ]
        self.assertEqual(
            set(source_schemas),
            {
                "RepositoryAnalysisOutputV1",
                "TestArchitectureOutputV1",
                "BrowserAgentOutputV1",
            },
        )
        self.assertIn(
            "bounded change context",
            report["findings"][0]["correlation_reason"],
        )
        evidence_uris = {
            item["uri"] for item in report["findings"][0]["evidence_refs"]
        }
        self.assertTrue(any(uri.startswith("artifact://github/") for uri in evidence_uris))
        self.assertTrue(any(uri.startswith("artifact://browser/") for uri in evidence_uris))
        self.assertEqual(
            failing_worker.requests[0].allowed_paths,
            ["/checkout", "/"],
        )
        self.assertTrue(
            any(
                "route-to-source causality remains unproven" in risk
                for risk in report["residual_risks"]
            )
        )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_terminal(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/v1/runs/{run_id}")
        if response.status_code == 200 and response.json()["status"] in {
            "completed",
            "failed",
            "cancelled",
        }:
            return response.json()
        time.sleep(0.01)
    raise AssertionError(f"Run {run_id} did not reach a terminal state")


if __name__ == "__main__":
    unittest.main()
