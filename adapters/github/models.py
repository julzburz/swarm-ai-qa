from __future__ import annotations

from typing import Literal

from pydantic import Field

from schemas.common import EvidenceRefV1, NonEmptyStr, StrictModel


class GitHubTreeEntryV1(StrictModel):
    path: NonEmptyStr
    sha: NonEmptyStr
    size: int = Field(ge=0)


class GitHubCapturedFileV1(StrictModel):
    path: NonEmptyStr
    sha: NonEmptyStr
    size: int = Field(ge=0)
    content: str
    evidence_ref: EvidenceRefV1


class GitHubPullRequestFileV1(StrictModel):
    path: NonEmptyStr
    status: Literal["added", "modified", "removed", "renamed", "copied", "changed", "unchanged"]
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changes: int = Field(ge=0)
    patch: str | None = None


class GitHubPullRequestSnapshotV1(StrictModel):
    number: int = Field(gt=0)
    title: NonEmptyStr
    base_sha: NonEmptyStr
    head_sha: NonEmptyStr
    base_branch: NonEmptyStr
    head_branch: NonEmptyStr
    files: list[GitHubPullRequestFileV1]
    files_truncated: bool = False
    evidence_ref: EvidenceRefV1


class GitHubInspectionV1(StrictModel):
    owner: NonEmptyStr
    repository: NonEmptyStr
    default_branch: NonEmptyStr
    private: bool
    commit_sha: NonEmptyStr
    tree_entries: list[GitHubTreeEntryV1]
    tree_truncated: bool = False
    captured_files: list[GitHubCapturedFileV1] = Field(default_factory=list)
    excluded_paths: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    pull_request: GitHubPullRequestSnapshotV1 | None = None
    tree_evidence_ref: EvidenceRefV1
