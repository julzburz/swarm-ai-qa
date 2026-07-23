from __future__ import annotations

import re
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from .common import Confidence, EvidenceRefV1, NonEmptyStr, ObservationCertainty, StrictModel


GITHUB_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
GITHUB_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class RepositoryTargetV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    repository_id: NonEmptyStr
    provider: Literal["github"] = "github"
    owner: NonEmptyStr
    name: NonEmptyStr
    clone_url: AnyHttpUrl
    default_branch: NonEmptyStr = "main"
    private: bool = False
    installation_ref: NonEmptyStr | None = None

    @field_validator("owner")
    @classmethod
    def validate_github_owner(cls, value: str) -> str:
        if not GITHUB_OWNER_PATTERN.fullmatch(value):
            raise ValueError("owner must be a canonical GitHub owner")
        return value

    @field_validator("name")
    @classmethod
    def validate_github_repository_name(cls, value: str) -> str:
        if not GITHUB_REPOSITORY_PATTERN.fullmatch(value) or value in {".", ".."}:
            raise ValueError("name must be a canonical GitHub repository name")
        return value

    @model_validator(mode="after")
    def identifiers_describe_the_same_repository(self) -> "RepositoryTargetV1":
        expected_id = f"github:{self.owner}/{self.name}"
        if self.repository_id.casefold() != expected_id.casefold():
            raise ValueError(f"repository_id must be {expected_id}")

        url = self.clone_url
        normalized_path = url.path.rstrip("/")
        if normalized_path.casefold().endswith(".git"):
            normalized_path = normalized_path[:-4]
        expected_path = f"/{self.owner}/{self.name}"
        if (
            url.scheme != "https"
            or (url.host or "").casefold() != "github.com"
            or url.username is not None
            or url.password is not None
            or url.port not in {None, 443}
            or url.query is not None
            or url.fragment is not None
            or normalized_path.casefold() != expected_path.casefold()
        ):
            raise ValueError(
                "clone_url must be the canonical HTTPS GitHub URL for owner/name"
            )
        return self


class PullRequestContextV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    number: int = Field(gt=0)
    base_sha: NonEmptyStr
    head_sha: NonEmptyStr
    base_branch: NonEmptyStr
    head_branch: NonEmptyStr
    title: NonEmptyStr
    changed_files: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def shas_must_differ(self) -> "PullRequestContextV1":
        if self.base_sha == self.head_sha:
            raise ValueError("base_sha and head_sha must differ")
        return self


class TechnologyDetectionV1(StrictModel):
    name: NonEmptyStr
    version: NonEmptyStr | None = None
    certainty: ObservationCertainty
    confidence: Confidence
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @model_validator(mode="after")
    def certainty_matches_confidence(self) -> "TechnologyDetectionV1":
        if self.certainty == ObservationCertainty.CONFIRMED and self.confidence < 0.9:
            raise ValueError("confirmed technology requires confidence >= 0.90")
        if self.certainty == ObservationCertainty.UNKNOWN and self.confidence > 0.5:
            raise ValueError("unknown technology cannot have confidence > 0.50")
        return self


class ProjectCommandV1(StrictModel):
    purpose: Literal["install", "build", "test", "lint", "typecheck", "e2e", "start"]
    command: NonEmptyStr
    working_directory: NonEmptyStr = "."
    source_ref: EvidenceRefV1
    discovered_only: bool = True
    execution_authorized: bool = False

    @model_validator(mode="after")
    def discovery_does_not_authorize_execution(self) -> "ProjectCommandV1":
        if self.discovered_only and self.execution_authorized:
            raise ValueError("A discovered-only command cannot be execution-authorized")
        return self


class ProjectComponentV1(StrictModel):
    component_id: NonEmptyStr
    path: NonEmptyStr
    component_type: Literal["frontend", "backend", "api", "library", "worker", "mobile", "infrastructure", "unknown"]
    languages: list[TechnologyDetectionV1] = Field(min_length=1)
    frameworks: list[TechnologyDetectionV1] = Field(default_factory=list)
    runtimes: list[TechnologyDetectionV1] = Field(default_factory=list)
    package_managers: list[TechnologyDetectionV1] = Field(default_factory=list)
    test_frameworks: list[TechnologyDetectionV1] = Field(default_factory=list)
    commands: list[ProjectCommandV1] = Field(default_factory=list)


class ProjectProfileV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: UUID = Field(default_factory=uuid4)
    repository_id: NonEmptyStr | None = None
    project_type: Literal["single_component", "monorepo", "polyglot", "runtime_only", "unknown"]
    components: list[ProjectComponentV1]
    infrastructure: list[TechnologyDetectionV1] = Field(default_factory=list)
    ci_systems: list[TechnologyDetectionV1] = Field(default_factory=list)
    overall_confidence: Confidence
    unknowns: list[NonEmptyStr] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def repository_profiles_need_components(self) -> "ProjectProfileV1":
        if self.project_type != "runtime_only" and not self.components:
            raise ValueError("Repository project profiles require at least one component")
        ids = [component.component_id for component in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("component_id values must be unique")
        return self


class ImpactedSurfaceV1(StrictModel):
    surface_id: NonEmptyStr
    component_id: NonEmptyStr
    paths: list[NonEmptyStr] = Field(min_length=1)
    user_journeys: list[NonEmptyStr] = Field(default_factory=list)
    risk_hypotheses: list[NonEmptyStr] = Field(default_factory=list)
    confidence: Confidence
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class ChangeImpactMapV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    change_id: NonEmptyStr
    impacted_surfaces: list[ImpactedSurfaceV1]
    unaffected_claims: list[NonEmptyStr] = Field(default_factory=list)
    global_risk: Literal["low", "medium", "high", "critical"]
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("impacted_surfaces")
    @classmethod
    def require_impact(cls, value: list[ImpactedSurfaceV1]) -> list[ImpactedSurfaceV1]:
        if not value:
            raise ValueError("A change impact map requires at least one impacted surface")
        return value


class ExistingTestV1(StrictModel):
    component_id: NonEmptyStr
    framework: NonEmptyStr
    test_type: Literal["unit", "integration", "e2e", "contract", "unknown"]
    path: NonEmptyStr
    command_ref: NonEmptyStr | None = None


class ExistingTestInventoryV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    tests: list[ExistingTestV1] = Field(default_factory=list)
    coverage_known: bool = False
    coverage_percent: float | None = Field(default=None, ge=0, le=100)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def coverage_value_requires_known_coverage(self) -> "ExistingTestInventoryV1":
        if self.coverage_percent is not None and not self.coverage_known:
            raise ValueError("coverage_percent requires coverage_known=true")
        return self


class RepositorySnapshotV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    repository_id: NonEmptyStr
    commit_sha: NonEmptyStr
    root_tree_ref: EvidenceRefV1
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    captured_paths: list[NonEmptyStr] = Field(default_factory=list)
    excluded_paths: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)


class RepositoryContextV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    target: RepositoryTargetV1
    snapshot: RepositorySnapshotV1
    pull_request: PullRequestContextV1 | None = None
    profile: ProjectProfileV1 | None = None
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class RiskHypothesisV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    hypothesis_id: NonEmptyStr
    component_id: NonEmptyStr
    description: NonEmptyStr
    quality_domains: set[NonEmptyStr] = Field(min_length=1)
    likelihood: Confidence
    potential_impact: Literal["low", "medium", "high", "critical"]
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    proposed_verification: NonEmptyStr
