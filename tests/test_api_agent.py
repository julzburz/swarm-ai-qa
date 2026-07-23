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
)
from schemas.mission import UserMissionRequestV1
from workers.api import (
    ApiContractDiscoveryV1,
    ApiOperationProbeV1,
    ApiWorkerRequestV1,
    ApiWorkerResultV1,
    SafeHttpApiWorker,
)


class ApiWorkerIntegrationTests(unittest.IsolatedAsyncioTestCase):
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
        cls.thread = threading.Thread(
            target=cls.server.run,
            daemon=True,
        )
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
        raise RuntimeError("API demo server did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    async def test_discovers_openapi_validates_get_and_blocks_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = await SafeHttpApiWorker(
                Path(temp_dir) / "artifacts"
            ).run(
                ApiWorkerRequestV1(
                    run_id=uuid4(),
                    task_id=uuid4(),
                    base_url=f"http://127.0.0.1:{self.port}",
                    allowed_paths=["/openapi.json", "/api"],
                    blocked_paths=[],
                    allow_private_network=True,
                    max_requests=10,
                    max_operations=10,
                    timeout_seconds=10,
                )
            )

            by_path = {
                operation.path: operation
                for operation in result.operations
            }
            self.assertTrue(result.contract.discovered)
            self.assertTrue(result.contract.valid)
            self.assertEqual(
                by_path["/api/status"].status,
                "passed",
            )
            self.assertTrue(
                by_path["/api/status"].schema_valid
            )
            self.assertEqual(
                by_path["/api/contract-mismatch"].status,
                "failed",
            )
            self.assertFalse(
                by_path["/api/contract-mismatch"].schema_valid
            )
            self.assertEqual(
                by_path["/api/redirect-external"].status,
                "blocked",
            )
            self.assertTrue(
                any(
                    "POST /api/items: mutating method prohibited"
                    in blocked
                    for blocked in result.blocked_operations
                )
            )
            self.assertEqual(result.request_count, 4)
            report = Path(result.report_path).read_text(
                encoding="utf-8"
            )
            self.assertNotIn('"state": 7', report)
            self.assertNotIn('"status": "ok"', report)

    async def test_without_contract_runs_only_allowlisted_get_smoke(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = await SafeHttpApiWorker(
                Path(temp_dir) / "artifacts"
            ).run(
                ApiWorkerRequestV1(
                    run_id=uuid4(),
                    task_id=uuid4(),
                    base_url=f"http://127.0.0.1:{self.port}",
                    allowed_paths=["/api/status"],
                    allow_private_network=True,
                    max_requests=5,
                    max_operations=5,
                    timeout_seconds=10,
                )
            )

            self.assertFalse(result.contract.discovered)
            self.assertEqual(result.request_count, 1)
            self.assertEqual(len(result.operations), 1)
            self.assertEqual(
                result.operations[0].source,
                "observed_get",
            )
            self.assertEqual(result.operations[0].status, "passed")
            self.assertIsNone(result.operations[0].schema_valid)


class FixtureApiWorker:
    def __init__(
        self,
        artifact_dir: Path,
        *,
        fail_schema: bool = False,
    ) -> None:
        self.artifact_dir = artifact_dir
        self.fail_schema = fail_schema
        self.requests: list[ApiWorkerRequestV1] = []

    async def run(
        self,
        request: ApiWorkerRequestV1,
    ) -> ApiWorkerResultV1:
        self.requests.append(request)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        report = self.artifact_dir / "safe-api-results.json"
        report.write_text(
            '{"response_values_persisted":false}',
            encoding="utf-8",
        )
        base_url = str(request.base_url).rstrip("/")
        return ApiWorkerResultV1(
            contract=ApiContractDiscoveryV1(
                discovered=True,
                valid=True,
                source_url=f"{base_url}/openapi.json",
                title="Fixture API",
                version="1.0.0",
                openapi_version="3.1.0",
                total_operations=2,
                safe_operations=1,
                mutating_operations=1,
            ),
            operations=[
                ApiOperationProbeV1(
                    operation_id="getStatus",
                    method="GET",
                    path="/api/status",
                    source="openapi",
                    status=(
                        "failed" if self.fail_schema else "passed"
                    ),
                    requested_url=f"{base_url}/api/status",
                    final_url=f"{base_url}/api/status",
                    status_code=200,
                    latency_ms=8,
                    expected_statuses=["200"],
                    schema_valid=not self.fail_schema,
                    observation=(
                        "The JSON body did not match the schema."
                        if self.fail_schema
                        else "The response matched status and JSON schema."
                    ),
                )
            ],
            blocked_operations=[
                "POST /api/items: mutating method prohibited"
            ],
            report_path=str(report),
            request_count=2,
            httpx_version="fixture",
            jsonschema_version="fixture",
        )


class ApiAgentSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.store = SQLiteRunStore(root / "api-agent.db")
        self.worker = FixtureApiWorker(root / "api-artifacts")

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_api_mission_reports_contract_coverage_and_traceability(
        self,
    ) -> None:
        mission = UserMissionRequestV1(
            objective="Validate the public API contract safely",
            mode=MissionMode.TARGETED_EXAMINATION,
            runtime_target=RuntimeTargetV1(
                base_url="https://staging.example.com",
                environment=Environment.STAGING,
                allowed_paths=["/openapi.json", "/api"],
            ),
            selected_domains={QualityDomain.API},
        )
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                api_worker=self.worker,
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
            state = _wait_for_terminal(
                client,
                accepted.json()["run_id"],
            )

        self.assertEqual(state["status"], "completed")
        outputs = {
            record["agent_id"]: record["output"]
            for record in state["task_records"].values()
        }
        api = outputs["api_test_engineer"]
        self.assertEqual(
            api["output_schema"],
            "ApiAgentOutputV1",
        )
        coverage = api["output"]["coverage"]
        self.assertTrue(coverage["contract_discovered"])
        self.assertTrue(coverage["contract_valid"])
        self.assertEqual(coverage["executed_operations"], 1)
        self.assertEqual(
            coverage["mutating_operations_blocked"],
            1,
        )
        self.assertFalse(coverage["unsafe_requests_performed"])
        report = outputs["evidence_reporting_analyst"]["output"][
            "report"
        ]
        self.assertEqual(
            set(report["coverage"]["executed_domains"]),
            {"api"},
        )
        case = next(
            result
            for result in report["test_case_results"]
            if result["case_id"] == "TC-API-001"
        )
        self.assertEqual(case["status"], "passed")
        self.assertTrue(case["evidence_refs"])
        self.assertEqual(
            self.worker.requests[0].allowed_paths,
            ["/openapi.json", "/api"],
        )

    def test_schema_mismatch_becomes_finding_and_failed_case(
        self,
    ) -> None:
        root = Path(self.temp_dir.name)
        failing_worker = FixtureApiWorker(
            root / "failing-api-artifacts",
            fail_schema=True,
        )
        mission = UserMissionRequestV1(
            objective="Detect a documented API schema mismatch",
            mode=MissionMode.TARGETED_EXAMINATION,
            runtime_target=RuntimeTargetV1(
                base_url="https://staging.example.com",
                environment=Environment.STAGING,
                allowed_paths=["/openapi.json", "/api"],
            ),
            selected_domains={QualityDomain.API},
        )
        app = create_app(
            store=self.store,
            registry=build_automation_registry(
                api_worker=failing_worker,
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
            state = _wait_for_terminal(
                client,
                accepted.json()["run_id"],
            )

        outputs = {
            record["agent_id"]: record["output"]
            for record in state["task_records"].values()
        }
        api = outputs["api_test_engineer"]["output"]
        self.assertEqual(len(api["findings"]), 1)
        report = outputs["evidence_reporting_analyst"]["output"][
            "report"
        ]
        api_finding = next(
            finding
            for finding in report["findings"]
            if finding["primary_finding"]["domain"] == "api"
        )
        self.assertIn(
            "bounded GET/HEAD validation",
            api_finding["correlation_reason"],
        )
        case = next(
            result
            for result in report["test_case_results"]
            if result["case_id"] == "TC-API-001"
        )
        self.assertEqual(case["status"], "failed")
        self.assertEqual(len(case["finding_ids"]), 1)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_terminal(
    client: TestClient,
    run_id: str,
) -> dict:
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
    raise AssertionError(
        f"Run {run_id} did not reach a terminal state"
    )


if __name__ == "__main__":
    unittest.main()
