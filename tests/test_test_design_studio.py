from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.app import create_app
from executors import build_automation_registry, build_github_registry
from orchestrator import SQLiteRunStore
from schemas.common import (
    Environment,
    MissionMode,
    QualityDomain,
    RuntimeTargetV1,
)
from schemas.execution import TestCaseExecutionV1
from schemas.mission import UserMissionRequestV1
from tests.test_accessibility_agent import FixtureAccessibilityWorker
from tests.test_browser_worker import FixtureBrowserWorker
from tests.test_github_slice import (
    FixtureGitHubClient,
    fixture_inspection,
    repository_target,
)
from tests.test_performance_agent import FixturePerformanceWorker
from tests.test_security_agent import FixtureSecurityWorker


class TestDesignStudioApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.root = root
        self.store = SQLiteRunStore(root / "test-design.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_runtime_matrix_separates_automated_and_manual_results(
        self,
    ) -> None:
        mission = UserMissionRequestV1(
            objective=(
                "Design and execute a traceable checkout QA campaign"
            ),
            mode=MissionMode.TARGETED_EXAMINATION,
            runtime_target=RuntimeTargetV1(
                base_url="https://staging.example.com",
                environment=Environment.STAGING,
                allowed_paths=["/checkout"],
            ),
            selected_domains={
                QualityDomain.FUNCTIONAL,
                QualityDomain.ACCESSIBILITY,
                QualityDomain.SECURITY,
                QualityDomain.PERFORMANCE,
            },
        )
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                browser_worker=FixtureBrowserWorker(
                    self.root / "browser"
                ),
                accessibility_worker=FixtureAccessibilityWorker(
                    self.root / "accessibility"
                ),
                security_worker=FixtureSecurityWorker(
                    self.root / "security"
                ),
                performance_worker=FixturePerformanceWorker(
                    self.root / "performance"
                ),
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
        outputs = {
            record["agent_id"]: record["output"]
            for record in state["task_records"].values()
        }
        test_plan = outputs["test_architect"]["output"]["test_plan"]
        cases = test_plan["test_cases"]
        self.assertEqual(len(cases), 8)
        self.assertEqual(
            sum(case["execution_mode"] == "automated" for case in cases),
            4,
        )
        self.assertEqual(
            sum(case["execution_mode"] == "manual" for case in cases),
            4,
        )
        self.assertTrue(
            all(case["gherkin"].startswith("# language: es") for case in cases)
        )
        self.assertTrue(
            all("executed" not in case for case in cases)
        )

        report = outputs["evidence_reporting_analyst"]["output"]["report"]
        results = {
            result["case_id"]: result
            for result in report["test_case_results"]
        }
        self.assertEqual(results["TC-FUNCTIONAL-001"]["status"], "passed")
        self.assertEqual(
            results["TC-ACCESSIBILITY-001"]["status"],
            "failed",
        )
        self.assertEqual(results["TC-SECURITY-001"]["status"], "failed")
        self.assertEqual(
            results["TC-PERFORMANCE-001"]["status"],
            "observed",
        )
        manual = [
            result
            for result in results.values()
            if result["status"] == "manual_required"
        ]
        self.assertEqual(len(manual), 4)
        self.assertTrue(
            all(
                not result["evidence_refs"]
                and result["executed_by"] is None
                for result in manual
            )
        )
        self.assertIn(
            "Test Design Studio trazó 8 caso(s)",
            report["execution_summary"],
        )

    def test_repository_case_is_observed_with_evidence(self) -> None:
        mission = UserMissionRequestV1(
            objective="Design a repository QA campaign",
            mode=MissionMode.TARGETED_EXAMINATION,
            repository_target=repository_target(),
            selected_domains={QualityDomain.REPOSITORY},
        )
        app = create_app(
            store=self.store,
            registry=build_github_registry(
                FixtureGitHubClient(fixture_inspection())
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

        outputs = {
            record["agent_id"]: record["output"]
            for record in state["task_records"].values()
        }
        test_plan = outputs["test_architect"]["output"]["test_plan"]
        self.assertEqual(
            [case["case_id"] for case in test_plan["test_cases"]],
            ["TC-REPOSITORY-001"],
        )
        result = outputs["evidence_reporting_analyst"]["output"]["report"][
            "test_case_results"
        ][0]
        self.assertEqual(result["status"], "observed")
        self.assertTrue(result["evidence_refs"])

    def test_manual_case_cannot_claim_automated_execution(self) -> None:
        with self.assertRaises(ValidationError):
            TestCaseExecutionV1(
                case_id="TC-MANUAL-001",
                status="manual_required",
                observation="Human validation remains pending.",
                executed_by="browser_automation_engineer",
            )


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
