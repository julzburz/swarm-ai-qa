from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from api.app import create_app
from api.config import ApiSettings
from api.results import artifact_id_for
from orchestrator import RuleBasedQaDirector, SQLiteRunStore
from orchestrator.models import RunStateV1, RunStatus, TaskExecutionRecordV1
from schemas.common import (
    Environment,
    EvidenceRefV1,
    MissionMode,
    QualityDomain,
    RuntimeTargetV1,
    Severity,
    TaskStatus,
)
from schemas.evidence import AgentOutputEnvelopeV1, CorrelatedFindingV1, FindingV1
from schemas.execution import CoverageSummaryV1
from schemas.mission import UserMissionRequestV1
from schemas.reporting import QaRunReportV1


class ResultsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.artifact_root = self.root / "artifacts"
        self.store = SQLiteRunStore(self.root / "results-api.db")
        self.state, self.local_ref, self.external_ref, self.local_path = (
            _completed_run_with_results(self.artifact_root)
        )
        self.store.save_run(self.state)
        self.app = create_app(
            settings=ApiSettings(artifact_root=self.artifact_root),
            store=self.store,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_findings_support_domain_severity_and_pagination(self) -> None:
        with TestClient(self.app) as client:
            response = client.get(
                f"/v1/runs/{self.state.run_id}/findings"
                "?domain=security&severity=medium&limit=1&offset=0"
            )
            empty = client.get(
                f"/v1/runs/{self.state.run_id}/findings"
                "?domain=accessibility"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["run_id"], str(self.state.run_id))
        self.assertEqual(body["run_status"], "completed")
        self.assertEqual(body["total"], 1)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(
            body["items"][0]["primary_finding"]["rule_id"],
            "header-csp",
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["total"], 0)

    def test_artifact_catalog_distinguishes_local_and_external_evidence(
        self,
    ) -> None:
        with TestClient(self.app) as client:
            response = client.get(
                f"/v1/runs/{self.state.run_id}/artifacts"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["downloadable"], 1)
        by_uri = {item["uri"]: item for item in body["items"]}
        local = by_uri[self.local_ref.uri]
        external = by_uri[self.external_ref.uri]
        self.assertTrue(local["available"])
        self.assertTrue(local["download_url"].endswith(local["artifact_id"]))
        self.assertFalse(external["available"])
        self.assertIsNone(external["download_url"])
        self.assertNotIn(str(self.artifact_root), response.text)

    def test_download_verifies_membership_hash_and_response_headers(
        self,
    ) -> None:
        artifact_id = artifact_id_for(self.local_ref.uri)
        with TestClient(self.app) as client:
            response = client.get(
                f"/v1/runs/{self.state.run_id}/artifacts/{artifact_id}"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'{"redacted":true}')
        self.assertEqual(
            response.headers["content-type"],
            "application/json",
        )
        self.assertEqual(
            response.headers["cache-control"],
            "private, no-store",
        )
        self.assertEqual(
            response.headers["x-content-type-options"],
            "nosniff",
        )
        self.assertIn(
            "attachment;",
            response.headers["content-disposition"],
        )

    def test_download_rejects_tampered_or_non_materialized_artifact(
        self,
    ) -> None:
        self.local_path.write_bytes(b"tampered")
        local_id = artifact_id_for(self.local_ref.uri)
        external_id = artifact_id_for(self.external_ref.uri)
        with TestClient(self.app) as client:
            tampered = client.get(
                f"/v1/runs/{self.state.run_id}/artifacts/{local_id}"
            )
            external = client.get(
                f"/v1/runs/{self.state.run_id}/artifacts/{external_id}"
            )
            unrelated = client.get(
                f"/v1/runs/{self.state.run_id}/artifacts/"
                + "0" * 64
            )

        self.assertEqual(tampered.status_code, 409)
        self.assertEqual(external.status_code, 410)
        self.assertEqual(unrelated.status_code, 404)

    def test_results_endpoints_are_bearer_protected(self) -> None:
        api_key = "results-api-key-with-at-least-32-characters"
        app = create_app(
            settings=ApiSettings(
                artifact_root=self.artifact_root,
                api_key=api_key,
            ),
            store=self.store,
        )
        with TestClient(app) as client:
            findings = client.get(
                f"/v1/runs/{self.state.run_id}/findings"
            )
            artifacts = client.get(
                f"/v1/runs/{self.state.run_id}/artifacts"
            )
            authorized = client.get(
                f"/v1/runs/{self.state.run_id}/artifacts",
                headers={"Authorization": f"Bearer {api_key}"},
            )

        self.assertEqual(findings.status_code, 401)
        self.assertEqual(artifacts.status_code, 401)
        self.assertEqual(authorized.status_code, 200)


def _completed_run_with_results(
    artifact_root: Path,
) -> tuple[RunStateV1, EvidenceRefV1, EvidenceRefV1, Path]:
    mission = UserMissionRequestV1(
        objective="Expose persisted findings and evidence",
        mode=MissionMode.TARGETED_EXAMINATION,
        runtime_target=RuntimeTargetV1(
            base_url="https://example.com",
            environment=Environment.STAGING,
            allowed_paths=["/"],
        ),
        selected_domains={QualityDomain.SECURITY},
    )
    plan = RuleBasedQaDirector().build_plan(mission)
    run_id = uuid4()
    security_task = next(
        task
        for task in plan.tasks
        if task.agent_id == "security_test_engineer"
    )
    reporting_task = next(
        task
        for task in plan.tasks
        if task.agent_id == "evidence_reporting_analyst"
    )
    content = b'{"redacted":true}'
    local_path = (
        artifact_root
        / str(run_id)
        / str(security_task.task_id)
        / "security"
        / "passive-security-results.json"
    )
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(content)
    local_ref = EvidenceRefV1(
        uri=(
            f"artifact://security/{run_id}/{security_task.task_id}/"
            "passive/passive-security-results.json"
        ),
        media_type="application/json",
        sha256=hashlib.sha256(content).hexdigest(),
        redacted=True,
        description="Redacted passive security results",
    )
    external_ref = EvidenceRefV1(
        uri="artifact://github/acme/shop/tree/headsha",
        media_type="application/json",
        sha256=hashlib.sha256(b"tree").hexdigest(),
        description="External GitHub evidence reference",
    )
    finding = FindingV1(
        run_id=run_id,
        task_id=security_task.task_id,
        reported_by="security_test_engineer",
        domain=QualityDomain.SECURITY,
        title="Content Security Policy is missing",
        severity=Severity.MEDIUM,
        confidence=0.98,
        observation="The response did not include Content-Security-Policy.",
        impact="The browser lacks a defense-in-depth control.",
        reproduction_steps=["Inspect the allowlisted response headers."],
        evidence_refs=[local_ref],
        recommendation="Define and test a restrictive CSP.",
        affected_locations=["https://example.com/"],
        rule_id="header-csp",
    )
    correlated = CorrelatedFindingV1(
        primary_finding=finding,
        final_confidence=finding.confidence,
        correlation_reason="Passive signal preserved.",
        evidence_refs=[local_ref],
    )
    report = QaRunReportV1(
        run_id=run_id,
        mission_summary=mission.objective,
        execution_summary="Security evidence persisted without code changes.",
        findings=[correlated],
        coverage=CoverageSummaryV1(
            plan_id=plan.plan_id,
            total_objectives=1,
            completed_objectives=1,
            executed_domains={QualityDomain.SECURITY},
            evidence_completeness=1.0,
        ),
        artifact_refs=[local_ref, external_ref],
    )
    task_records: dict[str, TaskExecutionRecordV1] = {}
    for task in plan.tasks:
        if task.task_id == reporting_task.task_id:
            envelope = AgentOutputEnvelopeV1(
                run_id=run_id,
                task_id=task.task_id,
                agent_id=task.agent_id,
                output_schema="EvidenceReportingOutputV1",
                output={
                    "report": report.model_dump(mode="json"),
                    "source_output_schemas": ["SecurityAgentOutputV1"],
                },
                evidence_refs=[local_ref, external_ref],
            )
        elif task.task_id == security_task.task_id:
            envelope = AgentOutputEnvelopeV1(
                run_id=run_id,
                task_id=task.task_id,
                agent_id=task.agent_id,
                output_schema="SecurityAgentOutputV1",
                output={"fixture": True},
                evidence_refs=[local_ref, external_ref],
            )
        else:
            envelope = AgentOutputEnvelopeV1(
                run_id=run_id,
                task_id=task.task_id,
                agent_id=task.agent_id,
                output_schema="FixtureOutputV1",
                output={"fixture": True},
            )
        task_records[str(task.task_id)] = TaskExecutionRecordV1(
            task_id=task.task_id,
            agent_id=task.agent_id,
            status=TaskStatus.COMPLETED,
            attempts=1,
            output=envelope,
        )
    return (
        RunStateV1(
            run_id=run_id,
            mission=mission,
            plan=plan,
            status=RunStatus.COMPLETED,
            task_records=task_records,
        ),
        local_ref,
        external_ref,
        local_path,
    )


if __name__ == "__main__":
    unittest.main()
