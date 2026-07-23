from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field

from schemas.common import NonEmptyStr, StrictModel


class ApiWorkerRequestV1(StrictModel):
    run_id: UUID
    task_id: UUID
    base_url: AnyHttpUrl
    allowed_paths: list[NonEmptyStr] = Field(min_length=1)
    blocked_paths: list[NonEmptyStr] = Field(default_factory=list)
    allow_private_network: bool = False
    max_requests: int = Field(gt=0, le=100)
    max_operations: int = Field(gt=0, le=50, default=20)
    max_response_bytes: int = Field(
        gt=0,
        le=5_000_000,
        default=1_000_000,
    )
    timeout_seconds: int = Field(gt=0, le=86_400)


class ApiContractDiscoveryV1(StrictModel):
    discovered: bool
    valid: bool | None = None
    source_url: NonEmptyStr | None = None
    title: str = ""
    version: str = ""
    openapi_version: str = ""
    structural_errors: list[NonEmptyStr] = Field(default_factory=list)
    total_operations: int = Field(ge=0)
    safe_operations: int = Field(ge=0)
    mutating_operations: int = Field(ge=0)


class ApiOperationProbeV1(StrictModel):
    operation_id: NonEmptyStr
    method: Literal["GET", "HEAD"]
    path: NonEmptyStr
    source: Literal["openapi", "observed_get"]
    status: Literal["passed", "failed", "blocked"]
    requested_url: NonEmptyStr
    final_url: NonEmptyStr
    status_code: int | None = Field(default=None, ge=100, le=599)
    latency_ms: int | None = Field(default=None, ge=0)
    expected_statuses: list[NonEmptyStr] = Field(default_factory=list)
    schema_valid: bool | None = None
    observation: NonEmptyStr


class ApiWorkerResultV1(StrictModel):
    contract: ApiContractDiscoveryV1
    operations: list[ApiOperationProbeV1] = Field(default_factory=list)
    blocked_operations: list[NonEmptyStr] = Field(default_factory=list)
    report_path: NonEmptyStr
    request_count: int = Field(ge=0)
    httpx_version: NonEmptyStr
    jsonschema_version: NonEmptyStr
    policy_version: Literal["safe-api-contract-v1"] = (
        "safe-api-contract-v1"
    )
