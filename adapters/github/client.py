from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
from typing import Any, Protocol

import httpx

from schemas.common import EvidenceRefV1
from schemas.project import RepositoryTargetV1

from .models import (
    GitHubCapturedFileV1,
    GitHubInspectionV1,
    GitHubPullRequestFileV1,
    GitHubPullRequestSnapshotV1,
    GitHubTreeEntryV1,
)


GITHUB_API_VERSION = "2026-03-10"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RELEVANT_FILENAMES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "poetry.lock",
    "pdm.lock",
    "uv.lock",
    "cargo.toml",
    "cargo.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "composer.json",
    "gemfile",
    "dockerfile",
}


class GitHubReadClient(Protocol):
    async def inspect(
        self,
        target: RepositoryTargetV1,
        pull_request_number: int | None = None,
    ) -> GitHubInspectionV1: ...


class GitHubApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message)


class GitHubRestClient:
    """Bounded GitHub REST reader. This class never issues mutation requests."""

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str = "https://api.github.com",
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        max_manifest_files: int = 32,
        max_file_bytes: int = 131_072,
        max_pr_pages: int = 10,
        allowed_private_repository_ids: set[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if max_manifest_files <= 0 or max_file_bytes <= 0 or max_pr_pages <= 0:
            raise ValueError("GitHub capture limits must be positive")
        self.token = token.strip() if token else None
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_manifest_files = max_manifest_files
        self.max_file_bytes = max_file_bytes
        self.max_pr_pages = max_pr_pages
        self.allowed_private_repository_ids = {
            value.casefold() for value in (allowed_private_repository_ids or set())
        }
        self.transport = transport

    @classmethod
    def from_env(cls) -> "GitHubRestClient":
        token = os.getenv("GITHUB_TOKEN", "").strip() or None
        base_url = os.getenv("GITHUB_API_URL", "https://api.github.com").strip()
        timeout = float(os.getenv("GITHUB_TIMEOUT_SECONDS", "15"))
        private_allowlist = {
            value.strip()
            for value in os.getenv(
                "SWARM_GITHUB_ALLOWED_PRIVATE_REPOSITORIES",
                "",
            ).split(",")
            if value.strip()
        }
        return cls(
            token=token,
            base_url=base_url,
            timeout_seconds=timeout,
            allowed_private_repository_ids=private_allowlist,
        )

    async def inspect(
        self,
        target: RepositoryTargetV1,
        pull_request_number: int | None = None,
    ) -> GitHubInspectionV1:
        if target.provider != "github":
            raise ValueError("GitHubRestClient only accepts github repository targets")
        if target.private and not self.token:
            raise GitHubApiError(
                "Private repositories require GITHUB_TOKEN with Contents: read permission",
                status_code=401,
            )
        if (
            target.private
            and target.repository_id.casefold() not in self.allowed_private_repository_ids
        ):
            raise GitHubApiError(
                "Private repository is not explicitly authorized for this GitHub token",
                status_code=403,
            )

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": "swarm-ai-qa/0.1",
        }
        # Public user-supplied targets never receive the server's private token.
        if target.private and self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
        ) as client:
            prefix = f"/repos/{target.owner}/{target.name}"
            repository = await self._get_json(client, prefix)
            actual_private = bool(repository.get("private", target.private))
            if actual_private != target.private:
                raise GitHubApiError(
                    "GitHub repository visibility does not match the authorized target",
                    status_code=403,
                )
            default_branch = str(repository.get("default_branch") or target.default_branch)
            commit = await self._get_json(client, f"{prefix}/commits/{default_branch}")
            commit_sha = _required_string(commit, "sha")
            tree = await self._get_json(
                client,
                f"{prefix}/git/trees/{commit_sha}",
                params={"recursive": "1"},
            )
            entries = self._tree_entries(tree)
            tree_ref = _evidence_ref(
                target.owner,
                target.name,
                "tree",
                commit_sha,
                json.dumps(tree, sort_keys=True).encode("utf-8"),
                f"GitHub tree at commit {commit_sha}",
            )
            captured, excluded = await self._capture_relevant_files(
                client,
                prefix,
                target,
                entries,
            )
            pull_request = None
            if pull_request_number is not None:
                pull_request = await self._read_pull_request(
                    client,
                    prefix,
                    target,
                    pull_request_number,
                )

        return GitHubInspectionV1(
            owner=target.owner,
            repository=target.name,
            default_branch=default_branch,
            private=actual_private,
            commit_sha=commit_sha,
            tree_entries=entries,
            tree_truncated=bool(tree.get("truncated", False)),
            captured_files=captured,
            excluded_paths=excluded,
            pull_request=pull_request,
            tree_evidence_ref=tree_ref,
        )

    async def _capture_relevant_files(
        self,
        client: httpx.AsyncClient,
        prefix: str,
        target: RepositoryTargetV1,
        entries: list[GitHubTreeEntryV1],
    ) -> tuple[list[GitHubCapturedFileV1], dict[str, str]]:
        candidates = [entry for entry in entries if _is_relevant_file(entry.path)]
        captured: list[GitHubCapturedFileV1] = []
        excluded: dict[str, str] = {}
        for entry in candidates:
            if len(captured) >= self.max_manifest_files:
                excluded[entry.path] = "manifest capture limit reached"
                continue
            if entry.size > self.max_file_bytes:
                excluded[entry.path] = f"file exceeds {self.max_file_bytes} byte limit"
                continue
            blob = await self._get_json(client, f"{prefix}/git/blobs/{entry.sha}")
            if blob.get("encoding") != "base64":
                excluded[entry.path] = "unsupported GitHub blob encoding"
                continue
            try:
                raw = base64.b64decode(str(blob.get("content", "")), validate=False)
                content = raw.decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                excluded[entry.path] = f"file is not decodable UTF-8: {type(exc).__name__}"
                continue
            evidence = _evidence_ref(
                target.owner,
                target.name,
                "file",
                entry.path,
                raw,
                f"Read-only capture of {entry.path}",
            )
            captured.append(
                GitHubCapturedFileV1(
                    path=entry.path,
                    sha=entry.sha,
                    size=entry.size,
                    content=content,
                    evidence_ref=evidence,
                )
            )
        return captured, excluded

    async def _read_pull_request(
        self,
        client: httpx.AsyncClient,
        prefix: str,
        target: RepositoryTargetV1,
        number: int,
    ) -> GitHubPullRequestSnapshotV1:
        pull = await self._get_json(client, f"{prefix}/pulls/{number}")
        files: list[GitHubPullRequestFileV1] = []
        files_truncated = False
        raw_pages: list[Any] = []
        for page in range(1, self.max_pr_pages + 1):
            page_data = await self._get_json(
                client,
                f"{prefix}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            if not isinstance(page_data, list):
                raise GitHubApiError("GitHub pull request files response must be a list")
            raw_pages.append(page_data)
            for item in page_data:
                files.append(
                    GitHubPullRequestFileV1(
                        path=_required_string(item, "filename"),
                        status=str(item.get("status", "modified")),
                        additions=int(item.get("additions", 0)),
                        deletions=int(item.get("deletions", 0)),
                        changes=int(item.get("changes", 0)),
                        patch=item.get("patch"),
                    )
                )
            if len(page_data) < 100:
                break
        else:
            files_truncated = True

        evidence_payload = json.dumps(
            {"pull": pull, "file_pages": raw_pages},
            sort_keys=True,
        ).encode("utf-8")
        return GitHubPullRequestSnapshotV1(
            number=number,
            title=_required_string(pull, "title"),
            base_sha=_required_string(pull.get("base", {}), "sha"),
            head_sha=_required_string(pull.get("head", {}), "sha"),
            base_branch=_required_string(pull.get("base", {}), "ref"),
            head_branch=_required_string(pull.get("head", {}), "ref"),
            files=files,
            files_truncated=files_truncated,
            evidence_ref=_evidence_ref(
                target.owner,
                target.name,
                "pull",
                str(number),
                evidence_payload,
                f"GitHub pull request #{number} metadata and changed files",
            ),
        )

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, str | int] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(path, params=params)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise GitHubApiError(
                        f"GitHub request failed: {type(exc).__name__}",
                        retryable=True,
                    ) from exc
                await asyncio.sleep(0.1 * (2**attempt))
                continue
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                await asyncio.sleep(_retry_delay(response, attempt))
                continue
            if response.is_error:
                message = _safe_error_message(response)
                raise GitHubApiError(
                    f"GitHub API returned {response.status_code}: {message}",
                    status_code=response.status_code,
                    retryable=response.status_code in RETRYABLE_STATUS_CODES,
                )
            try:
                return response.json()
            except ValueError as exc:
                raise GitHubApiError("GitHub API returned invalid JSON") from exc
        raise GitHubApiError(f"GitHub request failed: {last_error}", retryable=True)

    def _tree_entries(self, tree: Any) -> list[GitHubTreeEntryV1]:
        raw_entries = tree.get("tree", []) if isinstance(tree, dict) else []
        return [
            GitHubTreeEntryV1(
                path=_required_string(item, "path"),
                sha=_required_string(item, "sha"),
                size=int(item.get("size", 0)),
            )
            for item in raw_entries
            if item.get("type") == "blob"
        ]


def _required_string(data: Any, key: str) -> str:
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise GitHubApiError(f"GitHub response is missing required field: {key}")
    return value


def _is_relevant_file(path: str) -> bool:
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    return (
        name in RELEVANT_FILENAMES
        or name.startswith("requirements") and name.endswith(".txt")
        or name.endswith((".csproj", ".sln", ".gradle", ".gradle.kts"))
        or normalized.startswith(".github/workflows/") and name.endswith((".yml", ".yaml"))
    )


def _evidence_ref(
    owner: str,
    repository: str,
    kind: str,
    identity: str,
    raw: bytes,
    description: str,
) -> EvidenceRefV1:
    safe_identity = re.sub(r"[^A-Za-z0-9._/-]", "_", identity).strip("/") or "root"
    return EvidenceRefV1(
        uri=f"artifact://github/{owner}/{repository}/{kind}/{safe_identity}",
        media_type="application/json" if kind in {"tree", "pull"} else "text/plain",
        sha256=hashlib.sha256(raw).hexdigest(),
        description=description,
    )


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        return min(max(float(raw), 0.0), 5.0)
    except ValueError:
        return 0.1 * (2**attempt)


def _safe_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "request failed"
    message = payload.get("message") if isinstance(payload, dict) else None
    return str(message)[:300] if message else "request failed"
