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
from workers.accessibility import (
    AccessibilityPageScanV1,
    AccessibilityWorkerRequestV1,
    AccessibilityWorkerResultV1,
    AxeViolationNodeV1,
    AxeViolationV1,
    PlaywrightAxeWorker,
)
from tests.test_browser_worker import FixtureBrowserWorker


class AccessibilityWorkerIntegrationTests(unittest.IsolatedAsyncioTestCase):
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
                    ("127.0.0.1", cls.port),
                    timeout=0.1,
                ):
                    return
            except OSError:
                time.sleep(0.02)
        raise RuntimeError("Accessibility demo server did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    async def test_real_axe_scan_detects_only_automatable_violations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = PlaywrightAxeWorker(Path(temp_dir) / "artifacts")
            result = await worker.run(
                AccessibilityWorkerRequestV1(
                    run_id=uuid4(),
                    task_id=uuid4(),
                    base_url=f"http://127.0.0.1:{self.port}",
                    allowed_paths=["/healthy", "/inaccessible"],
                    allow_private_network=True,
                    max_requests=30,
                    timeout_seconds=10,
                )
            )

            by_path = {page.path: page for page in result.pages}
            inaccessible_rules = {
                violation.rule_id
                for violation in by_path["/inaccessible"].violations
            }
            self.assertFalse(by_path["/healthy"].violations)
            self.assertIn("html-has-lang", inaccessible_rules)
            self.assertIn("image-alt", inaccessible_rules)
            self.assertIn("button-name", inaccessible_rules)
            self.assertEqual(result.axe_version, "4.11.4")
            self.assertTrue(Path(result.report_path).is_file())
            self.assertGreater(by_path["/inaccessible"].rules_run, 0)


class FixtureAccessibilityWorker:
    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir
        self.requests: list[AccessibilityWorkerRequestV1] = []

    async def run(
        self,
        request: AccessibilityWorkerRequestV1,
    ) -> AccessibilityWorkerResultV1:
        self.requests.append(request)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        report = self.artifact_dir / "axe-results.json"
        report.write_text('{"redacted":true}', encoding="utf-8")
        return AccessibilityWorkerResultV1(
            pages=[
                AccessibilityPageScanV1(
                    path=path,
                    final_url=str(request.base_url).rstrip("/") + path,
                    http_status=200,
                    title="Fixture page",
                    axe_version="4.11.4",
                    duration_ms=20,
                    rules_run=50,
                    passes=49,
                    incomplete=0,
                    inapplicable=0,
                    violations=[
                        AxeViolationV1(
                            rule_id="button-name",
                            impact="serious",
                            description="Ensure buttons have discernible text",
                            help="Buttons must have discernible text",
                            help_url=(
                                "https://dequeuniversity.com/rules/axe/4.11/"
                                "button-name"
                            ),
                            tags=["wcag2a", "wcag412"],
                            nodes=[
                                AxeViolationNodeV1(
                                    target=["button.checkout"],
                                    failure_summary=(
                                        "Element does not have inner text that is "
                                        "visible to screen readers"
                                    ),
                                )
                            ],
                        )
                    ],
                )
                for path in request.allowed_paths
            ],
            report_path=str(report),
            request_count=len(request.allowed_paths),
            playwright_version="fixture",
            browser_version="fixture",
            axe_version="4.11.4",
            wcag_tags=request.wcag_tags,
        )


class AccessibilityApiSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.store = SQLiteRunStore(root / "accessibility-api.db")
        self.browser_worker = FixtureBrowserWorker(root / "browser-artifacts")
        self.accessibility_worker = FixtureAccessibilityWorker(
            root / "accessibility-artifacts"
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_browser_and_axe_evidence_are_correlated_by_url(self) -> None:
        mission = _accessibility_mission(
            {QualityDomain.FUNCTIONAL, QualityDomain.ACCESSIBILITY}
        )
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                browser_worker=self.browser_worker,
                accessibility_worker=self.accessibility_worker,
            ),
        )
        with TestClient(app) as client:
            preview = client.post(
                "/v1/plans/preview",
                json=mission.model_dump(mode="json"),
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
        accessibility = outputs["accessibility_specialist"]
        report = outputs["evidence_reporting_analyst"]["output"]["report"]
        self.assertEqual(
            accessibility["output_schema"],
            "AccessibilityAgentOutputV1",
        )
        self.assertEqual(
            accessibility["output"]["findings"][0]["rule_id"],
            "button-name",
        )
        self.assertFalse(
            accessibility["output"]["coverage"]["keyboard_checked"]
        )
        self.assertTrue(
            accessibility["output"]["verification_requests"]
        )
        correlation = next(
            item
            for item in report["findings"]
            if item["primary_finding"]["domain"] == "accessibility"
        )
        evidence_uris = {item["uri"] for item in correlation["evidence_refs"]}
        self.assertIn(
            "Playwright navigation evidence for the same URL",
            correlation["correlation_reason"],
        )
        self.assertTrue(
            any(uri.startswith("artifact://browser/") for uri in evidence_uris)
        )
        self.assertTrue(
            any(
                uri.startswith("artifact://accessibility/")
                for uri in evidence_uris
            )
        )
        self.assertEqual(
            set(report["coverage"]["executed_domains"]),
            {"functional", "accessibility"},
        )

    def test_accessibility_only_mission_uses_allowlisted_paths(self) -> None:
        mission = _accessibility_mission({QualityDomain.ACCESSIBILITY})
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                browser_worker=self.browser_worker,
                accessibility_worker=self.accessibility_worker,
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
            record["agent_id"]
            for record in state["task_records"].values()
        }
        self.assertIn("accessibility_specialist", agents)
        self.assertNotIn("browser_automation_engineer", agents)
        self.assertEqual(
            self.accessibility_worker.requests[0].allowed_paths,
            ["/checkout"],
        )


def _accessibility_mission(
    domains: set[QualityDomain],
) -> UserMissionRequestV1:
    return UserMissionRequestV1(
        objective="Detect accessibility barriers in checkout",
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
