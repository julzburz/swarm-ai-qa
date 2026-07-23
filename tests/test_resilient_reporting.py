from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from api import create_app
from api.config import ApiSettings
from api.runtime_reconnaissance import inspect_runtime
from executors import build_automation_registry
from orchestrator import SQLiteRunStore
from schemas.common import (
    Environment,
    MissionMode,
    QualityDomain,
    RuntimeTargetV1,
)
from schemas.mission import UserMissionRequestV1


class _FailingAccessibilityWorker:
    async def run(self, request):
        raise RuntimeError("axe infrastructure unavailable")


class _RuntimeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url: str):
        path = httpx.URL(url).path
        request = httpx.Request("GET", url)
        if path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=(
                    '<a href="/pricing">Pricing</a>'
                    '<a href="/docs">Docs</a>'
                    '<a href="https://other.example/offsite">Offsite</a>'
                ),
                request=request,
            )
        return httpx.Response(404, request=request)


class ResilientReportingTests(unittest.TestCase):
    def test_failed_specialist_still_produces_professional_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SQLiteRunStore(root / "runs.db")
            settings = ApiSettings(
                sqlite_path=root / "runs.db",
                artifact_root=root / "artifacts",
            )
            with patch.dict(
                os.environ,
                {"SWARM_ARTIFACT_ROOT": str(settings.artifact_root)},
            ):
                registry = build_automation_registry(
                    accessibility_worker=_FailingAccessibilityWorker()
                )
            app = create_app(
                settings=settings,
                store=store,
                registry=registry,
            )
            mission = UserMissionRequestV1(
                objective="Verificar accesibilidad y documentar limitaciones",
                mode=MissionMode.TARGETED_EXAMINATION,
                runtime_target=RuntimeTargetV1(
                    base_url="https://example.com",
                    environment=Environment.STAGING,
                    allowed_paths=["/"],
                ),
                selected_domains={QualityDomain.ACCESSIBILITY},
            )
            with TestClient(app) as client:
                preview = client.post(
                    "/v1/plans/preview",
                    json=mission.model_dump(mode="json"),
                )
                self.assertEqual(preview.status_code, 200)
                accepted = client.post(
                    "/v1/runs",
                    json={
                        "mission": preview.json()["mission"],
                        "approved": True,
                        "approved_plan_id": preview.json()["plan"]["plan_id"],
                    },
                )
                self.assertEqual(accepted.status_code, 202)
                run_id = accepted.json()["run_id"]
                state = None
                for _ in range(80):
                    state = client.get(f"/v1/runs/{run_id}").json()
                    if state["status"] in {
                        "completed_with_warnings",
                        "failed",
                    }:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(state)
                self.assertEqual(
                    state["status"],
                    "completed_with_warnings",
                )
                records = list(state["task_records"].values())
                reporter = next(
                    record
                    for record in records
                    if record["agent_id"] == "evidence_reporting_analyst"
                )
                self.assertEqual(reporter["status"], "completed")
                report = reporter["output"]["output"]["report"]
                self.assertEqual(report["verdict"], "inconclusive")
                self.assertTrue(report["limitations"])
                artifacts = client.get(
                    f"/v1/runs/{run_id}/artifacts"
                ).json()
                formats = {
                    item["media_type"]
                    for item in artifacts["items"]
                    if item["produced_by"] == "evidence_reporting_analyst"
                }
                self.assertIn("text/markdown", formats)
                self.assertIn("text/html", formats)
            store.close()

    def test_runtime_reconnaissance_expands_safe_same_origin_paths(self) -> None:
        target = RuntimeTargetV1(
            base_url="https://example.com",
            environment=Environment.PRODUCTION,
            allowed_paths=["/"],
            blocked_paths=["/admin"],
        )

        async def exercise():
            with (
                patch(
                    "api.runtime_reconnaissance.ensure_safe_runtime_destination",
                    new=AsyncMock(),
                ),
                patch(
                    "api.runtime_reconnaissance.httpx.AsyncClient",
                    return_value=_RuntimeClient(),
                ),
            ):
                return await inspect_runtime(
                    target,
                    MissionMode.TARGETED_EXAMINATION,
                )

        import asyncio

        result = asyncio.run(exercise())
        self.assertTrue(result.reachable)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.planned_paths,
            ["/", "/pricing", "/docs"],
        )
        self.assertNotIn("https://other.example/offsite", result.discovered_paths)


if __name__ == "__main__":
    unittest.main()
