from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.config import ApiSettings
from orchestrator import AgentRegistry, RuleBasedQaDirector, SQLiteRunStore
from orchestrator.models import RunStatus
from schemas.common import Environment, MissionMode, QualityDomain, RuntimeTargetV1
from schemas.evidence import AgentOutputEnvelopeV1
from schemas.mission import UserMissionRequestV1


class ApiAgent:
    def __init__(self, agent_id: str, delay: float = 0.001) -> None:
        self.agent_id = agent_id
        self.delay = delay

    async def execute(self, task, context):
        await asyncio.sleep(self.delay)
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema=f"{self.agent_id}.api-test.v1",
            output={"status": "ok"},
        )


def api_mission() -> UserMissionRequestV1:
    return UserMissionRequestV1(
        objective="Validar seguridad del entorno de staging",
        mode=MissionMode.TARGETED_EXAMINATION,
        runtime_target=RuntimeTargetV1(
            base_url="https://staging.example.com",
            environment=Environment.STAGING,
            allowed_paths=["/"],
        ),
        selected_domains={QualityDomain.SECURITY},
    )


def registry_for(mission: UserMissionRequestV1, delay: float = 0.001) -> AgentRegistry:
    plan = RuleBasedQaDirector().build_plan(mission)
    registry = AgentRegistry()
    for agent_id in plan.selected_agents:
        registry.register(ApiAgent(agent_id, delay=delay))
    return registry


class ControlPlaneApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SQLiteRunStore(Path(self.temp_dir.name) / "api.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_health_and_openapi_are_available(self) -> None:
        app = create_app(store=self.store)
        with TestClient(app) as client:
            health = client.get("/healthz")
            openapi = client.get("/openapi.json")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(health.json()["storage"], "sqlite")
        self.assertEqual(openapi.status_code, 200)
        self.assertIn("/v1/runs", openapi.json()["paths"])

    def test_plan_preview_reports_missing_executors(self) -> None:
        mission = api_mission()
        app = create_app(store=self.store)
        with TestClient(app) as client:
            response = client.post(
                "/v1/plans/preview",
                json=mission.model_dump(mode="json"),
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["executable"])
        self.assertIn("security_test_engineer", body["missing_executors"])

    def test_run_requires_explicit_approval(self) -> None:
        mission = api_mission()
        app = create_app(store=self.store, registry=registry_for(mission))
        with TestClient(app) as client:
            response = client.post(
                "/v1/runs",
                json={"mission": mission.model_dump(mode="json")},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "approval_required")

    def test_approved_run_rejects_missing_executors(self) -> None:
        mission = api_mission()
        app = create_app(store=self.store)
        with TestClient(app) as client:
            response = client.post(
                "/v1/runs",
                json={"mission": mission.model_dump(mode="json"), "approved": True},
            )

        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "missing_executors")
        self.assertIn("security_test_engineer", detail["agent_ids"])

    def test_run_state_event_history_and_terminal_sse(self) -> None:
        mission = api_mission()
        app = create_app(store=self.store, registry=registry_for(mission))
        with TestClient(app) as client:
            accepted = client.post(
                "/v1/runs",
                json={"mission": mission.model_dump(mode="json"), "approved": True},
            )
            self.assertEqual(accepted.status_code, 202)
            run_id = accepted.json()["run_id"]
            state = self._wait_for_terminal(client, run_id)
            history = client.get(f"/v1/runs/{run_id}/events")
            stream = client.get(f"/v1/runs/{run_id}/events/stream")

        self.assertEqual(state["status"], RunStatus.COMPLETED.value)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()[0]["event_type"], "run.created")
        self.assertEqual(history.json()[-1]["event_type"], "run.completed")
        self.assertIn("event: run.completed", stream.text)

    def test_active_run_can_be_cancelled(self) -> None:
        mission = api_mission()
        app = create_app(store=self.store, registry=registry_for(mission, delay=1.0))
        with TestClient(app) as client:
            accepted = client.post(
                "/v1/runs",
                json={"mission": mission.model_dump(mode="json"), "approved": True},
            )
            run_id = accepted.json()["run_id"]
            cancelling = client.post(f"/v1/runs/{run_id}/cancel")
            terminal = self._wait_for_terminal(client, run_id)

        self.assertEqual(cancelling.status_code, 200)
        self.assertTrue(cancelling.json()["cancellation_requested"])
        self.assertEqual(terminal["status"], RunStatus.CANCELLED.value)

    def _wait_for_terminal(self, client: TestClient, run_id: str) -> dict:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            response = client.get(f"/v1/runs/{run_id}")
            if response.status_code == 200:
                body = response.json()
                if body["status"] in {
                    RunStatus.COMPLETED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELLED.value,
                }:
                    return body
            time.sleep(0.01)
        self.fail(f"Run {run_id} did not reach a terminal state")


class ApiSettingsTests(unittest.TestCase):
    def test_auto_storage_uses_sqlite_without_database_url(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = ApiSettings.from_env(env_file=None)
        self.assertEqual(settings.storage_backend, "sqlite")

    def test_auto_storage_uses_neon_when_database_url_exists(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://user:secret@example.com/db"},
            clear=True,
        ):
            settings = ApiSettings.from_env(env_file=None)
        self.assertEqual(settings.storage_backend, "neon")

    def test_explicit_sqlite_overrides_configured_database_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://user:secret@example.com/db",
                "SWARM_STORAGE_BACKEND": "sqlite",
            },
            clear=True,
        ):
            settings = ApiSettings.from_env(env_file=None)
        self.assertEqual(settings.storage_backend, "sqlite")

    def test_explicit_neon_requires_database_url(self) -> None:
        with patch.dict(
            os.environ,
            {"SWARM_STORAGE_BACKEND": "neon"},
            clear=True,
        ), self.assertRaises(RuntimeError):
            ApiSettings.from_env(env_file=None)


if __name__ == "__main__":
    unittest.main()
