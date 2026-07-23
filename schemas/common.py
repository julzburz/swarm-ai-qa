from __future__ import annotations

from enum import StrEnum
from ipaddress import ip_address
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ArtifactUri = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^artifact://[a-z0-9_-]+/[A-Za-z0-9._/-]+$"),
]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
PositiveSeconds = Annotated[int, Field(gt=0, le=86_400)]


def is_forbidden_network_host(host: str) -> bool:
    """Reject local names and literal addresses that are unsafe for remote QA."""

    normalized = host.strip().lower().rstrip(".")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return not ip_address(normalized).is_global
    except ValueError:
        return False


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)


class MissionMode(StrEnum):
    QUICK_TASK = "quick_task"
    TARGETED_EXAMINATION = "targeted_examination"
    FULL_EXAMINATION = "full_examination"


class SourceType(StrEnum):
    REPOSITORY = "repository"
    RUNTIME = "runtime"
    COMBINED = "combined"


class Environment(StrEnum):
    LOCAL = "local"
    SANDBOX = "sandbox"
    STAGING = "staging"
    PRODUCTION = "production"


class QualityDomain(StrEnum):
    REPOSITORY = "repository"
    FUNCTIONAL = "functional"
    API = "api"
    SECURITY = "security"
    ACCESSIBILITY = "accessibility"
    PERFORMANCE = "performance"
    REGRESSION = "regression"
    RESILIENCE = "resilience"


class TaskStatus(StrEnum):
    PENDING = "pending"
    BLOCKED = "blocked"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class ObservationCertainty(StrEnum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class EvidenceRefV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    uri: ArtifactUri
    media_type: NonEmptyStr
    sha256: Annotated[str, StringConstraints(pattern=r"^[a-fA-F0-9]{64}$")] | None = None
    redacted: bool = False
    description: NonEmptyStr | None = None


class BudgetV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    max_duration_seconds: PositiveSeconds = 900
    max_requests: Annotated[int, Field(gt=0, le=100_000)] = 200
    max_llm_tokens: Annotated[int, Field(gt=0, le=10_000_000)] = 100_000
    max_parallel_tasks: Annotated[int, Field(gt=0, le=32)] = 4


class AuthorizationContextV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    authorization_id: UUID = Field(default_factory=uuid4)
    authorized_by: NonEmptyStr
    allowed_domains: list[NonEmptyStr] = Field(default_factory=list)
    allowed_repository_ids: list[NonEmptyStr] = Field(default_factory=list)
    allowed_paths: list[NonEmptyStr] = Field(default_factory=list)
    blocked_paths: list[NonEmptyStr] = Field(default_factory=list)
    allowed_actions: set[NonEmptyStr] = Field(default_factory=lambda: {"read"})
    expires_at: str | None = None

    @field_validator("allowed_domains")
    @classmethod
    def normalize_domains(cls, values: list[str]) -> list[str]:
        return [value.lower().rstrip(".") for value in values]


class RuntimeTargetV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    target_id: UUID = Field(default_factory=uuid4)
    base_url: AnyHttpUrl
    environment: Environment
    allowed_paths: list[NonEmptyStr] = Field(default_factory=lambda: ["/"])
    blocked_paths: list[NonEmptyStr] = Field(default_factory=list)
    test_account_secret_ref: NonEmptyStr | None = None
    allow_form_submission: bool = False
    allow_load_testing: bool = False
    allow_chaos_testing: bool = False

    @model_validator(mode="after")
    def assert_safe_defaults(self) -> "RuntimeTargetV1":
        host = self.base_url.host or ""
        if is_forbidden_network_host(host):
            raise ValueError(
                "runtime target must not use localhost, private, link-local, "
                "reserved or metadata addresses"
            )
        if self.environment == Environment.PRODUCTION and (
            self.allow_form_submission
            or self.allow_load_testing
            or self.allow_chaos_testing
        ):
            raise ValueError(
                "Production targets cannot enable form submission, load or "
                "chaos testing"
            )
        return self


class RunContextV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID = Field(default_factory=uuid4)
    mission_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    source_type: SourceType
    authorization: AuthorizationContextV1
    budget: BudgetV1 = Field(default_factory=BudgetV1)
