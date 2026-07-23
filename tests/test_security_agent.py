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
from schemas.common import (
    Environment,
    MissionMode,
    QualityDomain,
    RuntimeTargetV1,
    Severity,
)
from schemas.mission import UserMissionRequestV1
from tests.test_browser_worker import FixtureBrowserWorker
from tests.test_github_slice import (
    FixtureGitHubClient,
    fixture_inspection,
    repository_target,
)
from workers.security import (
    CookieObservationV1,
    PassiveHttpSecurityWorker,
    SecurityPageAuditV1,
    SecuritySignalV1,
    SecurityWorkerRequestV1,
    SecurityWorkerResultV1,
)


class SecurityWorkerIntegrationTests(unittest.IsolatedAsyncioTestCase):
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
        raise RuntimeError("Security demo server did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    async def test_passive_worker_detects_weak_headers_and_redacts_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = PassiveHttpSecurityWorker(Path(temp_dir) / "artifacts")
            result = await worker.run(
                SecurityWorkerRequestV1(
                    run_id=uuid4(),
                    task_id=uuid4(),
                    base_url=f"http://127.0.0.1:{self.port}",
                    allowed_paths=["/security-weak"],
                    allow_private_network=True,
                    max_requests=5,
                    timeout_seconds=10,
                )
            )

            rules = {signal.rule_id for signal in result.pages[0].signals}
            self.assertIn("transport-https", rules)
            self.assertIn("header-csp", rules)
            self.assertIn("cors-wildcard-credentials", rules)
            self.assertIn("cookie-secure", rules)
            self.assertIn("cookie-httponly", rules)
            self.assertIn("cookie-samesite-none-secure", rules)
            self.assertEqual(result.request_count, 1)
            report = Path(result.report_path).read_text(encoding="utf-8")
            self.assertNotIn("must-never-appear-in-evidence", report)
            self.assertIn('"value_redacted": true', report)

    async def test_passive_worker_respects_allowlisted_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = await PassiveHttpSecurityWorker(
                Path(temp_dir) / "artifacts"
            ).run(
                SecurityWorkerRequestV1(
                    run_id=uuid4(),
                    task_id=uuid4(),
                    base_url=f"http://127.0.0.1:{self.port}",
                    allowed_paths=["/security-healthy"],
                    blocked_paths=["/security-weak"],
                    allow_private_network=True,
                    max_requests=5,
                    timeout_seconds=10,
                )
            )

            self.assertEqual(
                [page.path for page in result.pages],
                ["/security-healthy"],
            )
            rules = {signal.rule_id for signal in result.pages[0].signals}
            self.assertNotIn("header-csp", rules)
            self.assertNotIn("cookie-secure", rules)
            self.assertNotIn("cookie-httponly", rules)


class FixtureSecurityWorker:
    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir
        self.requests: list[SecurityWorkerRequestV1] = []

    async def run(
        self,
        request: SecurityWorkerRequestV1,
    ) -> SecurityWorkerResultV1:
        self.requests.append(request)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        report = self.artifact_dir / "passive-security-results.json"
        report.write_text(
            '{"cookie_value":"[REDACTED]"}',
            encoding="utf-8",
        )
        pages = [
            SecurityPageAuditV1(
                path=path,
                requested_url=str(request.base_url).rstrip("/") + path,
                final_url=str(request.base_url).rstrip("/") + path,
                http_status=200,
                content_type="text/html",
                cookies=[
                    CookieObservationV1(
                        name="fixture_session",
                        secure=False,
                        http_only=True,
                        same_site="lax",
                    )
                ],
                signals=[
                    SecuritySignalV1(
                        rule_id="cookie-secure",
                        title="Cookie fixture_session lacks Secure",
                        severity=Severity.MEDIUM,
                        confidence=0.99,
                        observation=(
                            "The Set-Cookie metadata omitted Secure; its value "
                            "was redacted."
                        ),
                        impact=(
                            "The cookie may be transmitted over an insecure "
                            "connection."
                        ),
                        recommendation="Set Secure and use HTTPS.",
                        affected_url=(
                            str(request.base_url).rstrip("/") + path
                        ),
                    )
                ],
                duration_ms=10,
            )
            for path in request.allowed_paths
        ]
        return SecurityWorkerResultV1(
            pages=pages,
            report_path=str(report),
            request_count=len(pages),
            httpx_version="fixture",
        )


class SecurityApiSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.store = SQLiteRunStore(root / "security-api.db")
        self.browser_worker = FixtureBrowserWorker(root / "browser-artifacts")
        self.security_worker = FixtureSecurityWorker(root / "security-artifacts")

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_browser_and_passive_security_evidence_are_correlated_by_url(
        self,
    ) -> None:
        mission = _security_mission(
            {QualityDomain.FUNCTIONAL, QualityDomain.SECURITY}
        )
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                browser_worker=self.browser_worker,
                security_worker=self.security_worker,
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
        security = outputs["security_test_engineer"]
        report = outputs["evidence_reporting_analyst"]["output"]["report"]
        self.assertEqual(
            security["output_schema"],
            "SecurityAgentOutputV1",
        )
        self.assertFalse(
            security["output"]["coverage"][
                "active_exploitation_performed"
            ]
        )
        self.assertTrue(security["output"]["verification_requests"])
        correlation = next(
            item
            for item in report["findings"]
            if item["primary_finding"]["domain"] == "security"
        )
        evidence_uris = {item["uri"] for item in correlation["evidence_refs"]}
        self.assertIn(
            "exact allowlisted URL",
            correlation["correlation_reason"],
        )
        self.assertTrue(
            any(uri.startswith("artifact://browser/") for uri in evidence_uris)
        )
        self.assertTrue(
            any(uri.startswith("artifact://security/") for uri in evidence_uris)
        )
        self.assertEqual(
            set(report["coverage"]["executed_domains"]),
            {"functional", "security"},
        )

    def test_security_only_mission_uses_allowlisted_paths(self) -> None:
        mission = _security_mission({QualityDomain.SECURITY})
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                browser_worker=self.browser_worker,
                security_worker=self.security_worker,
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
        self.assertIn("security_test_engineer", agents)
        self.assertNotIn("browser_automation_engineer", agents)
        self.assertEqual(
            self.security_worker.requests[0].allowed_paths,
            ["/checkout"],
        )

    def test_repository_only_security_reports_scope_without_fake_scan(
        self,
    ) -> None:
        mission = UserMissionRequestV1(
            objective="Define the repository security review scope",
            mode=MissionMode.TARGETED_EXAMINATION,
            repository_target=repository_target(),
            selected_domains={QualityDomain.SECURITY},
        )
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                github_client=FixtureGitHubClient(fixture_inspection()),
                browser_worker=self.browser_worker,
                security_worker=self.security_worker,
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
        security_record = next(
            record
            for record in state["task_records"].values()
            if record["agent_id"] == "security_test_engineer"
        )
        security = security_record["output"]["output"]
        self.assertEqual(
            security["coverage"]["mode"],
            "repository_scope_only",
        )
        self.assertTrue(
            security["coverage"]["repository_snapshot_observed"]
        )
        self.assertEqual(security["findings"], [])
        self.assertIn(
            "not static source scanning",
            security["residual_risks"][0],
        )
        self.assertEqual(self.security_worker.requests, [])


def _security_mission(
    domains: set[QualityDomain],
) -> UserMissionRequestV1:
    return UserMissionRequestV1(
        objective="Passively inspect the checkout security posture",
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
