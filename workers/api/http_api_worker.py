from __future__ import annotations

import importlib.metadata
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from jsonschema import RefResolver
from jsonschema.validators import validator_for

from workers.browser.playwright_worker import (
    ensure_safe_runtime_destination,
    url_is_allowed,
)

from .models import (
    ApiContractDiscoveryV1,
    ApiOperationProbeV1,
    ApiWorkerRequestV1,
    ApiWorkerResultV1,
)


SAFE_METHODS = {"get", "head"}
HTTP_METHODS = {
    "get",
    "head",
    "options",
    "post",
    "put",
    "patch",
    "delete",
}
REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 3


@dataclass(slots=True)
class _ResponseCapture:
    status_code: int
    content_type: str
    content: bytes
    final_url: str
    duration_ms: int
    requests_consumed: int


@dataclass(slots=True)
class _OperationSpec:
    operation_id: str
    method: str
    path: str
    operation: dict[str, Any]
    path_parameters: list[dict[str, Any]]


class _RequestPolicyError(ValueError):
    def __init__(
        self,
        message: str,
        requests_consumed: int = 0,
    ) -> None:
        super().__init__(message)
        self.requests_consumed = requests_consumed


class SafeHttpApiWorker:
    """Discover bounded OpenAPI contracts and execute GET/HEAD only."""

    def __init__(
        self,
        artifact_root: str | Path = ".data/artifacts",
    ) -> None:
        self.artifact_root = Path(artifact_root)

    async def run(
        self,
        request: ApiWorkerRequestV1,
    ) -> ApiWorkerResultV1:
        base_url = str(request.base_url)
        await ensure_safe_runtime_destination(
            base_url,
            allow_private_network=request.allow_private_network,
        )
        task_dir = (
            self.artifact_root
            / str(request.run_id)
            / str(request.task_id)
            / "api"
        )
        task_dir.mkdir(parents=True, exist_ok=True)
        report_path = task_dir / "safe-api-results.json"
        request_count = 0
        contract_document: dict[str, Any] | None = None
        contract_source: str | None = None

        timeout = httpx.Timeout(request.timeout_seconds)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={
                "Accept": "application/json, application/problem+json",
                "User-Agent": "Swarm-AI-QA-Safe-API/1.0",
            },
        ) as client:
            for candidate in _contract_candidates(request):
                if request_count >= request.max_requests:
                    break
                try:
                    response = await _bounded_request(
                        client,
                        "GET",
                        candidate,
                        request,
                        request.max_requests - request_count,
                    )
                except _RequestPolicyError as exc:
                    request_count += exc.requests_consumed
                    continue
                except httpx.HTTPError:
                    request_count += 1
                    continue
                request_count += response.requests_consumed
                document = _parse_contract_candidate(response)
                if document is not None:
                    contract_document = document
                    contract_source = _safe_url(response.final_url)
                    break

            contract, specs = _inspect_contract(
                contract_document,
                contract_source,
            )
            blocked_operations: list[str] = []
            probes: list[ApiOperationProbeV1] = []

            if contract_document is not None and contract.valid:
                selected = _select_operations(
                    specs,
                    request,
                    blocked_operations,
                )
                for spec in selected:
                    if len(probes) >= request.max_operations:
                        blocked_operations.append(
                            f"{spec.operation_id}: operation budget exceeded"
                        )
                        continue
                    if request_count >= request.max_requests:
                        probes.append(
                            _blocked_probe(
                                spec,
                                base_url,
                                "Request budget exhausted before execution.",
                            )
                        )
                        continue
                    probe, consumed = await _execute_operation(
                        client,
                        request,
                        spec,
                        contract_document,
                        request.max_requests - request_count,
                    )
                    probes.append(probe)
                    request_count += consumed
                    client.cookies.clear()
            else:
                for path in _unique_paths(request.allowed_paths):
                    if len(probes) >= request.max_operations:
                        blocked_operations.append(
                            f"GET {path}: operation budget exceeded"
                        )
                        continue
                    spec = _OperationSpec(
                        operation_id=f"observed:get:{path}",
                        method="get",
                        path=path,
                        operation={},
                        path_parameters=[],
                    )
                    if request_count >= request.max_requests:
                        probes.append(
                            _blocked_probe(
                                spec,
                                base_url,
                                "Request budget exhausted before execution.",
                            )
                        )
                        continue
                    probe, consumed = await _execute_operation(
                        client,
                        request,
                        spec,
                        None,
                        request.max_requests - request_count,
                    )
                    probes.append(probe)
                    request_count += consumed
                    client.cookies.clear()

        if not contract.discovered or contract.valid is False:
            contract = contract.model_copy(
                update={
                    "total_operations": max(
                        contract.total_operations,
                        len(probes),
                    ),
                    "safe_operations": max(
                        contract.safe_operations,
                        len(probes),
                    ),
                }
            )
        result = ApiWorkerResultV1(
            contract=contract,
            operations=probes,
            blocked_operations=sorted(set(blocked_operations)),
            report_path=str(report_path.resolve()),
            request_count=request_count,
            httpx_version=importlib.metadata.version("httpx"),
            jsonschema_version=importlib.metadata.version("jsonschema"),
        )
        report_path.write_text(
            json.dumps(
                result.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return result


def _contract_candidates(
    request: ApiWorkerRequestV1,
) -> list[str]:
    base_url = str(request.base_url)
    paths: list[str] = []
    for configured in _unique_paths(request.allowed_paths):
        lowered = configured.lower()
        if "openapi" in lowered or "swagger" in lowered:
            paths.append(configured)
        prefix = configured.rstrip("/")
        if prefix in {"/api", "/v1", "/v2", "/v3"}:
            paths.append(f"{prefix}/openapi.json")
    paths.extend(
        [
            "/openapi.json",
            "/swagger.json",
            "/api/openapi.json",
        ]
    )
    candidates = [
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        for path in dict.fromkeys(paths)
    ]
    return [
        candidate
        for candidate in candidates
        if url_is_allowed(
            candidate,
            base_url,
            request.allowed_paths,
            request.blocked_paths,
        )
    ][:5]


def _parse_contract_candidate(
    response: _ResponseCapture,
) -> dict[str, Any] | None:
    if response.status_code >= 400 or not response.content:
        return None
    content_type = response.content_type.lower()
    if "json" not in content_type:
        return None
    try:
        document = json.loads(response.content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    if "openapi" not in document and "swagger" not in document:
        return None
    return document


def _inspect_contract(
    document: dict[str, Any] | None,
    source_url: str | None,
) -> tuple[ApiContractDiscoveryV1, list[_OperationSpec]]:
    if document is None:
        return (
            ApiContractDiscoveryV1(
                discovered=False,
                total_operations=0,
                safe_operations=0,
                mutating_operations=0,
            ),
            [],
        )
    errors: list[str] = []
    version = document.get("openapi") or document.get("swagger")
    if not isinstance(version, str) or not version.strip():
        errors.append("OpenAPI/Swagger version is missing or invalid.")
    info = document.get("info")
    if not isinstance(info, dict):
        errors.append("OpenAPI info object is missing or invalid.")
        info = {}
    paths = document.get("paths")
    if not isinstance(paths, dict):
        errors.append("OpenAPI paths object is missing or invalid.")
        paths = {}

    specs: list[_OperationSpec] = []
    safe_count = 0
    mutating_count = 0
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            errors.append("OpenAPI contains an invalid path item.")
            continue
        path_parameters = _parameter_list(path_item.get("parameters"))
        for method, operation in path_item.items():
            lowered = str(method).lower()
            if lowered not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = str(
                operation.get("operationId") or f"{lowered.upper()} {path}"
            )
            specs.append(
                _OperationSpec(
                    operation_id=operation_id,
                    method=lowered,
                    path=path,
                    operation=operation,
                    path_parameters=path_parameters,
                )
            )
            if lowered in SAFE_METHODS:
                safe_count += 1
            else:
                mutating_count += 1
    title = str(info.get("title") or "")[:200]
    api_version = str(info.get("version") or "")[:100]
    return (
        ApiContractDiscoveryV1(
            discovered=True,
            valid=not errors,
            source_url=source_url,
            title=title,
            version=api_version,
            openapi_version=str(version or "")[:50],
            structural_errors=errors,
            total_operations=len(specs),
            safe_operations=safe_count,
            mutating_operations=mutating_count,
        ),
        specs,
    )


def _select_operations(
    specs: list[_OperationSpec],
    request: ApiWorkerRequestV1,
    blocked_operations: list[str],
) -> list[_OperationSpec]:
    selected: list[_OperationSpec] = []
    base_url = str(request.base_url)
    for spec in specs:
        descriptor = f"{spec.method.upper()} {spec.path}"
        if spec.method not in SAFE_METHODS:
            blocked_operations.append(
                f"{descriptor}: mutating method prohibited"
            )
            continue
        target = urljoin(
            base_url.rstrip("/") + "/",
            spec.path.lstrip("/"),
        )
        if not url_is_allowed(
            target,
            base_url,
            request.allowed_paths,
            request.blocked_paths,
        ):
            blocked_operations.append(
                f"{descriptor}: outside route allowlist"
            )
            continue
        parameters = [
            *spec.path_parameters,
            *_parameter_list(spec.operation.get("parameters")),
        ]
        if _requires_test_data(spec, parameters):
            blocked_operations.append(
                f"{descriptor}: required parameters need explicit test data"
            )
            selected.append(spec)
            continue
        selected.append(spec)
    return selected


async def _execute_operation(
    client: httpx.AsyncClient,
    request: ApiWorkerRequestV1,
    spec: _OperationSpec,
    contract: dict[str, Any] | None,
    remaining_budget: int,
) -> tuple[ApiOperationProbeV1, int]:
    base_url = str(request.base_url)
    target = urljoin(
        base_url.rstrip("/") + "/",
        spec.path.lstrip("/"),
    )
    parameters = [
        *spec.path_parameters,
        *_parameter_list(spec.operation.get("parameters")),
    ]
    if _requires_test_data(spec, parameters):
        return (
            _blocked_probe(
                spec,
                base_url,
                "Required parameters need explicitly approved synthetic data.",
            ),
            0,
        )
    try:
        response = await _bounded_request(
            client,
            spec.method.upper(),
            target,
            request,
            remaining_budget,
        )
    except _RequestPolicyError as exc:
        return (
            ApiOperationProbeV1(
                operation_id=spec.operation_id,
                method=spec.method.upper(),
                path=spec.path,
                source=(
                    "openapi" if contract is not None else "observed_get"
                ),
                status="blocked",
                requested_url=_safe_url(target),
                final_url=_safe_url(target),
                observation=(
                    "The safe request could not be completed within policy: "
                    f"{type(exc).__name__}."
                ),
            ),
            exc.requests_consumed,
        )
    except httpx.HTTPError as exc:
        return (
            ApiOperationProbeV1(
                operation_id=spec.operation_id,
                method=spec.method.upper(),
                path=spec.path,
                source=(
                    "openapi" if contract is not None else "observed_get"
                ),
                status="blocked",
                requested_url=_safe_url(target),
                final_url=_safe_url(target),
                observation=(
                    "The safe request failed at the HTTP boundary: "
                    f"{type(exc).__name__}."
                ),
            ),
            1,
        )

    expected = _expected_statuses(spec.operation)
    status_matches = (
        _status_is_documented(response.status_code, expected)
        if contract is not None
        else 200 <= response.status_code < 400
    )
    schema_valid: bool | None = None
    schema_error_path = ""
    if contract is not None and spec.method != "head":
        schema = _response_schema(
            spec.operation,
            response.status_code,
            response.content_type,
            contract,
        )
        if schema is not None:
            schema_valid, schema_error_path = _validate_json_schema(
                response.content,
                schema,
                contract,
            )
    passed = status_matches and schema_valid is not False
    observation = (
        "The bounded read-only response matched the documented status"
        if contract is not None and status_matches
        else "The bounded GET/HEAD smoke returned a non-error status"
        if status_matches
        else "The response status was not accepted by the contract or safe smoke policy"
    )
    if schema_valid is True:
        observation += " and its JSON body matched the documented schema."
    elif schema_valid is False:
        observation += (
            " but its JSON body did not match the documented schema"
            + (
                f" at {schema_error_path}."
                if schema_error_path
                else "."
            )
        )
    else:
        observation += "; no supported JSON response schema was available."
    return (
        ApiOperationProbeV1(
            operation_id=spec.operation_id,
            method=spec.method.upper(),
            path=spec.path,
            source=(
                "openapi" if contract is not None else "observed_get"
            ),
            status="passed" if passed else "failed",
            requested_url=_safe_url(target),
            final_url=_safe_url(response.final_url),
            status_code=response.status_code,
            latency_ms=response.duration_ms,
            expected_statuses=expected,
            schema_valid=schema_valid,
            observation=observation,
        ),
        response.requests_consumed,
    )


async def _bounded_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    request: ApiWorkerRequestV1,
    remaining_budget: int,
) -> _ResponseCapture:
    current = url
    consumed = 0
    started = time.monotonic()
    for _ in range(MAX_REDIRECTS + 1):
        if consumed >= remaining_budget:
            raise _RequestPolicyError(
                "API request budget exhausted",
                consumed,
            )
        try:
            await ensure_safe_runtime_destination(
                current,
                allow_private_network=request.allow_private_network,
            )
        except ValueError as exc:
            raise _RequestPolicyError(
                str(exc),
                consumed,
            ) from exc
        if not url_is_allowed(
            current,
            str(request.base_url),
            request.allowed_paths,
            request.blocked_paths,
        ):
            raise _RequestPolicyError(
                "API request left the authorized allowlist",
                consumed,
            )
        async with client.stream(method, current) as response:
            consumed += 1
            content = bytearray()
            try:
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > request.max_response_bytes:
                        raise _RequestPolicyError(
                            "API response exceeded byte budget",
                            consumed,
                        )
            finally:
                client.cookies.clear()
            if response.status_code in REDIRECT_CODES:
                location = response.headers.get("location")
                if not location:
                    raise _RequestPolicyError(
                        "API redirect omitted Location",
                        consumed,
                    )
                current = urljoin(current, location)
                continue
            return _ResponseCapture(
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
                content=bytes(content),
                final_url=_safe_url(str(response.url)),
                duration_ms=max(
                    0,
                    round((time.monotonic() - started) * 1000),
                ),
                requests_consumed=consumed,
            )
    raise _RequestPolicyError(
        "API redirect budget exhausted",
        consumed,
    )


def _blocked_probe(
    spec: _OperationSpec,
    base_url: str,
    reason: str,
) -> ApiOperationProbeV1:
    target = urljoin(
        base_url.rstrip("/") + "/",
        spec.path.lstrip("/"),
    )
    return ApiOperationProbeV1(
        operation_id=spec.operation_id,
        method=spec.method.upper(),
        path=spec.path,
        source="openapi",
        status="blocked",
        requested_url=_safe_url(target),
        final_url=_safe_url(target),
        observation=reason,
    )


def _expected_statuses(operation: dict[str, Any]) -> list[str]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return []
    return [str(status) for status in responses]


def _status_is_documented(
    status_code: int,
    expected: list[str],
) -> bool:
    text = str(status_code)
    if text in expected or "default" in {
        value.lower() for value in expected
    }:
        return True
    return any(
        len(value) == 3
        and value[0] == text[0]
        and value[1:].upper() == "XX"
        for value in expected
    )


def _response_schema(
    operation: dict[str, Any],
    status_code: int,
    content_type: str,
    document: dict[str, Any],
) -> dict[str, Any] | None:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    response = (
        responses.get(str(status_code))
        or responses.get(f"{str(status_code)[0]}XX")
        or responses.get(f"{str(status_code)[0]}xx")
        or responses.get("default")
    )
    response = _resolve_pointer(response, document)
    if not isinstance(response, dict):
        return None
    content = response.get("content")
    if not isinstance(content, dict):
        schema = response.get("schema")
        return (
            _resolve_pointer(schema, document)
            if isinstance(schema, dict)
            else None
        )
    media_type = content_type.split(";", 1)[0].strip().lower()
    media = (
        content.get(media_type)
        or content.get("application/json")
        or next(
            (
                value
                for key, value in content.items()
                if key.endswith("+json")
            ),
            None,
        )
    )
    if not isinstance(media, dict):
        return None
    schema = media.get("schema")
    return (
        _resolve_pointer(schema, document)
        if isinstance(schema, dict)
        else None
    )


def _validate_json_schema(
    content: bytes,
    schema: dict[str, Any],
    document: dict[str, Any],
) -> tuple[bool, str]:
    try:
        instance = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "$"
    try:
        validator_class = validator_for(schema)
        validator_class.check_schema(schema)
        resolver = RefResolver.from_schema(document)
        error = next(
            validator_class(
                schema,
                resolver=resolver,
            ).iter_errors(instance),
            None,
        )
    except Exception:
        return False, "$schema"
    if error is None:
        return True, ""
    path = "$" + "".join(
        f"[{item}]" if isinstance(item, int) else f".{item}"
        for item in error.absolute_path
    )
    return False, path[:200]


def _resolve_pointer(
    value: Any,
    document: dict[str, Any],
) -> Any:
    if not isinstance(value, dict):
        return value
    reference = value.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return value
    current: Any = document
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            return value
        current = current[token]
    return current


def _parameter_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _requires_test_data(
    spec: _OperationSpec,
    parameters: list[dict[str, Any]],
) -> bool:
    if "{" in spec.path or "requestBody" in spec.operation:
        return True
    return any(
        "$ref" in parameter
        or (
            parameter.get("required")
            and parameter.get("in") in {
                "path",
                "query",
                "header",
                "cookie",
            }
        )
        for parameter in parameters
    )


def _unique_paths(paths: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            "/" + path.strip("/") if path != "/" else "/"
            for path in paths
        )
    )


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, "", "")
    )
