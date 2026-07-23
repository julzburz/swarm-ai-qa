from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from adapters.github import GitHubApiError, GitHubInspectionV1, GitHubRestClient
from adapters.github.models import (
    GitHubCapturedFileV1,
    GitHubPullRequestFileV1,
    GitHubPullRequestSnapshotV1,
    GitHubTreeEntryV1,
)
from api.app import create_app
from executors import build_github_registry
from orchestrator import SQLiteRunStore
from schemas.common import EvidenceRefV1, MissionMode, QualityDomain
from schemas.mission import MissionJobV1, UserMissionRequestV1
from schemas.project import RepositoryTargetV1


PACKAGE_JSON = json.dumps(
    {
        "scripts": {"test": "jest", "build": "next build"},
        "dependencies": {"next": "15.0.0", "react": "19.0.0"},
        "devDependencies": {"jest": "30.0.0"},
    }
)
MONOREPO_WEB_PACKAGE = json.dumps(
    {
        "scripts": {"test": "vitest", "build": "next build"},
        "dependencies": {"next": "15.0.0", "react": "19.0.0"},
        "devDependencies": {"vitest": "3.0.0"},
    }
)
MONOREPO_API_PYPROJECT = """
[project]
dependencies = ["fastapi", "uvicorn"]

[project.optional-dependencies]
test = ["pytest"]
""".strip()


def evidence(uri: str, content: str) -> EvidenceRefV1:
    return EvidenceRefV1(
        uri=uri,
        media_type="application/json",
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        description="Test fixture evidence",
    )


def repository_target(*, private: bool = False) -> RepositoryTargetV1:
    return RepositoryTargetV1(
        repository_id="github:acme/shop",
        owner="acme",
        name="shop",
        clone_url="https://github.com/acme/shop.git",
        private=private,
    )


def repository_mission() -> UserMissionRequestV1:
    return UserMissionRequestV1(
        objective="Inspect repository structure and pull-request impact",
        mode=MissionMode.QUICK_TASK,
        repository_target=repository_target(),
        pull_request_number=7,
        requested_jobs=[
            MissionJobV1(
                objective="Build an evidence-backed repository profile",
                domains={QualityDomain.REPOSITORY},
            )
        ],
    )


def fixture_inspection() -> GitHubInspectionV1:
    package_ref = evidence("artifact://github/acme/shop/file/package.json", PACKAGE_JSON)
    tree_ref = evidence("artifact://github/acme/shop/tree/headsha", "tree")
    pull_ref = evidence("artifact://github/acme/shop/pull/7", "pull")
    return GitHubInspectionV1(
        owner="acme",
        repository="shop",
        default_branch="main",
        private=False,
        commit_sha="headsha",
        tree_entries=[
            GitHubTreeEntryV1(path="package.json", sha="pkgsha", size=len(PACKAGE_JSON)),
            GitHubTreeEntryV1(path="src/app.tsx", sha="srcsha", size=120),
            GitHubTreeEntryV1(path="tests/app.test.tsx", sha="testsha", size=100),
        ],
        captured_files=[
            GitHubCapturedFileV1(
                path="package.json",
                sha="pkgsha",
                size=len(PACKAGE_JSON),
                content=PACKAGE_JSON,
                evidence_ref=package_ref,
            )
        ],
        pull_request=GitHubPullRequestSnapshotV1(
            number=7,
            title="Change checkout flow",
            base_sha="basesha",
            head_sha="headsha",
            base_branch="main",
            head_branch="checkout-update",
            files=[
                GitHubPullRequestFileV1(
                    path="src/checkout.tsx",
                    status="modified",
                    additions=12,
                    deletions=3,
                    changes=15,
                    patch="@@ -1 +1 @@",
                )
            ],
            evidence_ref=pull_ref,
        ),
        tree_evidence_ref=tree_ref,
    )


def monorepo_inspection() -> GitHubInspectionV1:
    web_ref = evidence(
        "artifact://github/acme/shop/file/apps/web/package.json",
        MONOREPO_WEB_PACKAGE,
    )
    api_ref = evidence(
        "artifact://github/acme/shop/file/services/api/pyproject.toml",
        MONOREPO_API_PYPROJECT,
    )
    tree_ref = evidence("artifact://github/acme/shop/tree/monorepo-head", "tree")
    pull_ref = evidence("artifact://github/acme/shop/pull/8", "pull")
    return GitHubInspectionV1(
        owner="acme",
        repository="shop",
        default_branch="main",
        private=False,
        commit_sha="monorepo-head",
        tree_entries=[
            GitHubTreeEntryV1(
                path="apps/web/package.json",
                sha="web-package",
                size=len(MONOREPO_WEB_PACKAGE),
            ),
            GitHubTreeEntryV1(
                path="apps/web/src/app/checkout/page.tsx",
                sha="web-source",
                size=200,
            ),
            GitHubTreeEntryV1(
                path="services/api/pyproject.toml",
                sha="api-project",
                size=len(MONOREPO_API_PYPROJECT),
            ),
            GitHubTreeEntryV1(
                path="services/api/app/main.py",
                sha="api-source",
                size=200,
            ),
            GitHubTreeEntryV1(
                path="README.md",
                sha="readme",
                size=50,
            ),
        ],
        captured_files=[
            GitHubCapturedFileV1(
                path="apps/web/package.json",
                sha="web-package",
                size=len(MONOREPO_WEB_PACKAGE),
                content=MONOREPO_WEB_PACKAGE,
                evidence_ref=web_ref,
            ),
            GitHubCapturedFileV1(
                path="services/api/pyproject.toml",
                sha="api-project",
                size=len(MONOREPO_API_PYPROJECT),
                content=MONOREPO_API_PYPROJECT,
                evidence_ref=api_ref,
            ),
        ],
        pull_request=GitHubPullRequestSnapshotV1(
            number=8,
            title="Update checkout and authentication",
            base_sha="base-monorepo",
            head_sha="monorepo-head",
            base_branch="main",
            head_branch="checkout-auth",
            files=[
                GitHubPullRequestFileV1(
                    path="apps/web/src/app/checkout/page.tsx",
                    status="modified",
                    additions=10,
                    deletions=2,
                    changes=12,
                ),
                GitHubPullRequestFileV1(
                    path="services/api/app/auth.py",
                    status="modified",
                    additions=8,
                    deletions=1,
                    changes=9,
                ),
            ],
            evidence_ref=pull_ref,
        ),
        tree_evidence_ref=tree_ref,
    )


class FixtureGitHubClient:
    def __init__(self, inspection: GitHubInspectionV1) -> None:
        self.inspection = inspection
        self.calls: list[tuple[str, int | None]] = []

    async def inspect(self, target, pull_request_number=None) -> GitHubInspectionV1:
        self.calls.append((target.repository_id, pull_request_number))
        return self.inspection


class GitHubRestClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_tree_manifest_and_pull_request_with_get_only(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            path = request.url.path
            if path == "/repos/acme/shop":
                return httpx.Response(200, json={"default_branch": "main", "private": False})
            if path == "/repos/acme/shop/commits/main":
                return httpx.Response(200, json={"sha": "headsha"})
            if path == "/repos/acme/shop/git/trees/headsha":
                return httpx.Response(
                    200,
                    json={
                        "truncated": False,
                        "tree": [
                            {"path": "package.json", "type": "blob", "sha": "pkgsha", "size": len(PACKAGE_JSON)},
                            {"path": "src/app.tsx", "type": "blob", "sha": "srcsha", "size": 100},
                        ],
                    },
                )
            if path == "/repos/acme/shop/git/blobs/pkgsha":
                encoded = base64.b64encode(PACKAGE_JSON.encode()).decode()
                return httpx.Response(200, json={"encoding": "base64", "content": encoded})
            if path == "/repos/acme/shop/pulls/7":
                return httpx.Response(
                    200,
                    json={
                        "title": "Change checkout flow",
                        "base": {"sha": "basesha", "ref": "main"},
                        "head": {"sha": "headsha", "ref": "checkout-update"},
                    },
                )
            if path == "/repos/acme/shop/pulls/7/files":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "filename": "src/checkout.tsx",
                            "status": "modified",
                            "additions": 12,
                            "deletions": 3,
                            "changes": 15,
                            "patch": "@@ -1 +1 @@",
                        }
                    ],
                )
            return httpx.Response(404, json={"message": "not found"})

        client = GitHubRestClient(transport=httpx.MockTransport(handler))
        result = await client.inspect(repository_target(), pull_request_number=7)

        self.assertEqual(result.commit_sha, "headsha")
        self.assertEqual(result.captured_files[0].path, "package.json")
        self.assertEqual(result.pull_request.files[0].path, "src/checkout.tsx")
        self.assertTrue(all(request.method == "GET" for request in requests))
        self.assertTrue(
            all(request.headers["X-GitHub-Api-Version"] == "2026-03-10" for request in requests)
        )
        self.assertTrue(all("authorization" not in request.headers for request in requests))

    async def test_private_repository_requires_token_before_network_access(self) -> None:
        client = GitHubRestClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
        with self.assertRaises(GitHubApiError) as caught:
            await client.inspect(repository_target(private=True))
        self.assertEqual(caught.exception.status_code, 401)

    async def test_private_repository_requires_explicit_server_allowlist(self) -> None:
        client = GitHubRestClient(
            token="server-token",
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        )
        with self.assertRaises(GitHubApiError) as caught:
            await client.inspect(repository_target(private=True))
        self.assertEqual(caught.exception.status_code, 403)

    async def test_public_repository_never_receives_server_token(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/repos/acme/shop":
                return httpx.Response(
                    200,
                    json={"default_branch": "main", "private": False},
                )
            if request.url.path.endswith("/commits/main"):
                return httpx.Response(200, json={"sha": "headsha"})
            if request.url.path.endswith("/git/trees/headsha"):
                return httpx.Response(200, json={"tree": [], "truncated": False})
            return httpx.Response(404, json={"message": "not found"})

        client = GitHubRestClient(
            token="server-token",
            transport=httpx.MockTransport(handler),
        )
        await client.inspect(repository_target())
        self.assertTrue(requests)
        self.assertTrue(
            all("authorization" not in request.headers for request in requests)
        )

    async def test_allowlisted_private_repository_receives_read_token(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/repos/acme/shop":
                return httpx.Response(
                    200,
                    json={"default_branch": "main", "private": True},
                )
            if request.url.path.endswith("/commits/main"):
                return httpx.Response(200, json={"sha": "headsha"})
            if request.url.path.endswith("/git/trees/headsha"):
                return httpx.Response(200, json={"tree": [], "truncated": False})
            return httpx.Response(404, json={"message": "not found"})

        client = GitHubRestClient(
            token="server-token",
            allowed_private_repository_ids={"github:acme/shop"},
            transport=httpx.MockTransport(handler),
        )
        result = await client.inspect(repository_target(private=True))
        self.assertTrue(result.private)
        self.assertTrue(
            all(
                request.headers.get("authorization") == "Bearer server-token"
                for request in requests
            )
        )

    async def test_retries_transient_github_failure(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            if request.url.path == "/repos/acme/shop":
                attempts += 1
                if attempts == 1:
                    return httpx.Response(503, json={"message": "temporarily unavailable"})
                return httpx.Response(200, json={"default_branch": "main", "private": False})
            if request.url.path.endswith("/commits/main"):
                return httpx.Response(200, json={"sha": "headsha"})
            if request.url.path.endswith("/git/trees/headsha"):
                return httpx.Response(200, json={"tree": [], "truncated": False})
            return httpx.Response(404, json={"message": "not found"})

        client = GitHubRestClient(transport=httpx.MockTransport(handler), max_retries=1)
        await client.inspect(repository_target())
        self.assertEqual(attempts, 2)


class GitHubVerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SQLiteRunStore(Path(self.temp_dir.name) / "github-slice.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_repository_mission_completes_with_profile_plan_and_report(self) -> None:
        fixture_client = FixtureGitHubClient(fixture_inspection())
        app = create_app(
            store=self.store,
            registry=build_github_registry(fixture_client),
        )
        mission = repository_mission()

        with TestClient(app) as client:
            preview = client.post(
                "/v1/plans/preview",
                json=mission.model_dump(mode="json"),
            )
            self.assertEqual(preview.status_code, 200)
            preview_body = preview.json()
            self.assertTrue(preview_body["executable"])
            self.assertEqual(
                preview_body["planning_basis"],
                "repository_reconnaissance",
            )
            self.assertEqual(
                preview_body["reconnaissance"]["project_profile"]["project_type"],
                "single_component",
            )
            self.assertNotIn(
                "stack pendiente de confirmar",
                preview_body["plan"]["summary"],
            )
            self.assertIn("Next.js", preview_body["plan"]["summary"])

            accepted = client.post(
                "/v1/runs",
                json={
                    "mission": mission.model_dump(mode="json"),
                    "approved": True,
                    "approved_plan_id": preview_body["plan"]["plan_id"],
                },
            )
            self.assertEqual(accepted.status_code, 202)
            self.assertEqual(
                accepted.json()["plan"]["plan_id"],
                preview_body["plan"]["plan_id"],
            )
            run_id = accepted.json()["run_id"]
            state = self._wait_for_terminal(client, run_id)
            events = client.get(f"/v1/runs/{run_id}/events").json()

        self.assertEqual(state["status"], "completed")
        outputs = {
            record["agent_id"]: record["output"]
            for record in state["task_records"].values()
        }
        repository = outputs["repository_analyst"]
        architecture = outputs["test_architect"]
        reporting = outputs["evidence_reporting_analyst"]
        self.assertEqual(repository["output_schema"], "RepositoryAnalysisOutputV1")
        component = repository["output"]["project_profile"]["components"][0]
        self.assertIn("TypeScript", [item["name"] for item in component["languages"]])
        self.assertIn("Next.js", [item["name"] for item in component["frameworks"]])
        self.assertEqual(architecture["output_schema"], "TestArchitectureOutputV1")
        self.assertEqual(reporting["output_schema"], "EvidenceReportingOutputV1")
        self.assertEqual(reporting["output"]["report"]["findings"], [])
        self.assertIn("no source files were modified", reporting["output"]["report"]["execution_summary"])
        self.assertEqual(fixture_client.calls, [("github:acme/shop", 7)])
        self.assertEqual(events[-1]["event_type"], "run.completed")

    def test_repository_analyst_separates_monorepo_components_and_change_impact(self) -> None:
        fixture_client = FixtureGitHubClient(monorepo_inspection())
        app = create_app(
            store=self.store,
            registry=build_github_registry(fixture_client),
        )
        mission = repository_mission().model_copy(
            update={"pull_request_number": 8}
        )

        with TestClient(app) as client:
            accepted = client.post(
                "/v1/runs",
                json={"mission": mission.model_dump(mode="json"), "approved": True},
            )
            state = self._wait_for_terminal(client, accepted.json()["run_id"])

        outputs = {
            record["agent_id"]: record["output"]
            for record in state["task_records"].values()
        }
        analysis = outputs["repository_analyst"]["output"]
        profile = analysis["project_profile"]
        self.assertEqual(profile["project_type"], "monorepo")
        components = {
            component["component_id"]: component
            for component in profile["components"]
        }
        self.assertEqual(set(components), {"apps-web", "services-api"})
        self.assertEqual(components["apps-web"]["component_type"], "frontend")
        self.assertEqual(components["services-api"]["component_type"], "api")
        self.assertEqual(
            components["apps-web"]["commands"][0]["working_directory"],
            "apps/web",
        )
        self.assertIn(
            "TypeScript",
            [item["name"] for item in components["apps-web"]["languages"]],
        )
        self.assertIn(
            "Python",
            [item["name"] for item in components["services-api"]["languages"]],
        )
        surfaces = {
            surface["component_id"]: surface["paths"]
            for surface in analysis["change_impact"]["impacted_surfaces"]
        }
        self.assertEqual(
            surfaces,
            {
                "apps-web": ["apps/web/src/app/checkout/page.tsx"],
                "services-api": ["services/api/app/auth.py"],
            },
        )
        web_surface = next(
            surface
            for surface in analysis["change_impact"]["impacted_surfaces"]
            if surface["component_id"] == "apps-web"
        )
        self.assertEqual(web_surface["user_journeys"], ["/checkout"])

    def _wait_for_terminal(self, client: TestClient, run_id: str) -> dict:
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
        self.fail(f"Run {run_id} did not reach a terminal state")


if __name__ == "__main__":
    unittest.main()
