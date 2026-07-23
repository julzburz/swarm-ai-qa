from __future__ import annotations

import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi.testclient import TestClient

from api.app import create_app
from demo_web.app import app as demo_app
from executors import build_automation_registry
from orchestrator import SQLiteRunStore
from schemas.common import Environment, MissionMode, QualityDomain, RuntimeTargetV1
from schemas.mission import UserMissionRequestV1
from tests.test_browser_worker import FixtureBrowserWorker
from workers.performance import (
    PerformanceSampleV1,
    PerformanceWorkerRequestV1,
    PerformanceWorkerResultV1,
    PlaywrightPerformanceWorker,
)


class PerformanceWorkerIntegrationTests(unittest.IsolatedAsyncioTestCase):
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
                with socket.create_connection(
                    ("127.0.0.1", cls.port), timeout=0.1
                ):
                    return
            except OSError:
                time.sleep(0.02)
        raise RuntimeError("Performance demo server did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    async def test_worker_runs_three_cold_context_read_only_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = await PlaywrightPerformanceWorker(
                Path(temp_dir) / "artifacts"
            ).run(
                PerformanceWorkerRequestV1(
                    run_id=uuid4(),
                    task_id=uuid4(),
                    base_url=f"http://127.0.0.1:{self.port}",
                    allowed_paths=["/healthy"],
                    allow_private_network=True,
                    repetitions=3,
                    max_requests=12,
                    timeout_seconds=10,
                )
            )

            self.assertEqual(len(result.samples), 3)
            self.assertTrue(
                all(sample.status == "passed" for sample in result.samples)
            )
            self.assertTrue(
                all(sample.ttfb_ms is not None for sample in result.samples)
            )
            self.assertTrue(
                all(sample.load_event_ms is not None for sample in result.samples)
            )
            self.assertLessEqual(result.request_count, 12)
            report = Path(result.report_path)
            self.assertTrue(report.is_file())
            report_text = report.read_text(encoding="utf-8")
            self.assertNotIn("<html", report_text.lower())
            self.assertIn('"network_profile": "native-cold-context"', report_text)


class FixturePerformanceWorker:
    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir
        self.requests: list[PerformanceWorkerRequestV1] = []

    async def run(
        self,
        request: PerformanceWorkerRequestV1,
    ) -> PerformanceWorkerResultV1:
        self.requests.append(request)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        report = self.artifact_dir / "performance-smoke-results.json"
        report.write_text('{"redacted":true}', encoding="utf-8")
        samples: list[PerformanceSampleV1] = []
        for path in request.allowed_paths:
            url = str(request.base_url).rstrip("/") + path
            for repetition in range(1, request.repetitions + 1):
                samples.append(
                    PerformanceSampleV1(
                        path=path,
                        final_url=url,
                        repetition=repetition,
                        http_status=200,
                        status="passed",
                        ttfb_ms=800 + repetition * 100,
                        dom_content_loaded_ms=1200 + repetition * 100,
                        load_event_ms=1500 + repetition * 100,
                        first_contentful_paint_ms=1800 + repetition * 100,
                        largest_contentful_paint_ms=2500 + repetition * 100,
                        cumulative_layout_shift=0.10 + repetition * 0.01,
                        transfer_bytes=100_000 + repetition * 1000,
                        resource_count=10,
                        duration_ms=1800,
                    )
                )
        return PerformanceWorkerResultV1(
            samples=samples,
            report_path=str(report),
            request_count=len(samples),
            playwright_version="fixture",
            browser_version="fixture",
        )


class PerformanceApiSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.store = SQLiteRunStore(root / "performance-api.db")
        self.browser_worker = FixtureBrowserWorker(root / "browser-artifacts")
        self.performance_worker = FixturePerformanceWorker(
            root / "performance-artifacts"
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_browser_and_performance_evidence_are_correlated_by_url(self) -> None:
        mission = _performance_mission(
            {QualityDomain.FUNCTIONAL, QualityDomain.PERFORMANCE}
        )
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                browser_worker=self.browser_worker,
                performance_worker=self.performance_worker,
            ),
        )
        with TestClient(app) as client:
            preview = client.post(
                "/v1/plans/preview", json=mission.model_dump(mode="json")
            )
            self.assertTrue(preview.json()["executable"])
            accepted = client.post(
                "/v1/runs",
                json={
                    "mission": mission.model_dump(mode="json"),
                    "approved": True,
                },
            )
            state = _wait_for_terminal(client, accepted.json()["run_id"])

        self.assertEqual(state["status"], "completed")
        outputs = {
            record["agent_id"]: record["output"]
            for record in state["task_records"].values()
        }
        performance = outputs["performance_test_engineer"]
        report = outputs["evidence_reporting_analyst"]["output"]["report"]
        self.assertEqual(
            performance["output_schema"], "PerformanceAgentOutputV1"
        )
        self.assertFalse(performance["output"]["baseline_compared"])
        self.assertFalse(performance["output"]["coverage"]["inp_measured"])
        self.assertFalse(
            performance["output"]["coverage"]["active_load_test_performed"]
        )
        self.assertEqual(
            performance["output"]["coverage"]["successful_samples"], 3
        )
        correlation = next(
            item
            for item in report["findings"]
            if item["primary_finding"]["domain"] == "performance"
        )
        evidence_uris = {item["uri"] for item in correlation["evidence_refs"]}
        self.assertIn(
            "exact allowlisted URL", correlation["correlation_reason"]
        )
        self.assertIn(
            "not a field-data or regression claim",
            correlation["correlation_reason"],
        )
        self.assertTrue(
            any(uri.startswith("artifact://browser/") for uri in evidence_uris)
        )
        self.assertTrue(
            any(
                uri.startswith("artifact://performance/")
                for uri in evidence_uris
            )
        )
        self.assertEqual(
            set(report["coverage"]["executed_domains"]),
            {"functional", "performance"},
        )

    def test_performance_only_mission_uses_allowlisted_paths(self) -> None:
        mission = _performance_mission({QualityDomain.PERFORMANCE})
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                browser_worker=self.browser_worker,
                performance_worker=self.performance_worker,
            ),
        )
        with TestClient(app) as client:
            accepted = client.post(
                "/v1/runs",
                json={
                    "mission": mission.model_dump(mode="json"),
                    "approved": True,
                },
            )
            state = _wait_for_terminal(client, accepted.json()["run_id"])

        self.assertEqual(state["status"], "completed")
        agents = {
            record["agent_id"] for record in state["task_records"].values()
        }
        self.assertIn("performance_test_engineer", agents)
        self.assertNotIn("browser_automation_engineer", agents)
        request = self.performance_worker.requests[0]
        self.assertEqual(request.allowed_paths, ["/checkout"])
        self.assertEqual(request.repetitions, 3)
        self.assertLessEqual(request.max_requests, 100)


def _performance_mission(
    domains: set[QualityDomain],
) -> UserMissionRequestV1:
    return UserMissionRequestV1(
        objective="Measure safe checkout performance signals",
        mode=MissionMode.TARGETED_EXAMINATION,
        runtime_target=RuntimeTargetV1(
            base_url="https://staging.example.com",
            environment=Environment.STAGING,
            allowed_paths=["/checkout"],
        ),
        selected_domains=domains,
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_terminal(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 5
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
