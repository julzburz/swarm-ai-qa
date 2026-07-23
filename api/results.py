from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from orchestrator.models import RunStateV1
from schemas.common import EvidenceRefV1, QualityDomain, Severity
from schemas.evidence import CorrelatedFindingV1
from schemas.reporting import QaRunReportV1

from .schemas import ArtifactListResponseV1, ArtifactSummaryV1, FindingListResponseV1


LOCAL_ARTIFACT_LAYOUT = {
    "browser": {
        "directory": "browser",
        "kinds": {"trace", "screenshot"},
    },
    "accessibility": {
        "directory": "accessibility",
        "kinds": {"axe"},
    },
    "security": {
        "directory": "security",
        "kinds": {"passive"},
    },
    "performance": {
        "directory": "performance",
        "kinds": {"smoke"},
    },
    "api": {
        "directory": "api",
        "kinds": {"contract"},
    },
    "report": {
        "directory": "report",
        "kinds": {"report"},
    },
}


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    ref: EvidenceRefV1
    produced_by: str
    task_id: UUID


def findings_response(
    state: RunStateV1,
    *,
    domain: QualityDomain | None,
    severity: Severity | None,
    limit: int,
    offset: int,
) -> FindingListResponseV1:
    findings = _report_findings(state)
    if domain is not None:
        findings = [
            item
            for item in findings
            if item.primary_finding.domain == domain
        ]
    if severity is not None:
        findings = [
            item
            for item in findings
            if item.primary_finding.severity == severity
        ]
    return FindingListResponseV1(
        run_id=state.run_id,
        run_status=state.status,
        total=len(findings),
        limit=limit,
        offset=offset,
        domain=domain,
        severity=severity,
        items=findings[offset : offset + limit],
    )


def artifacts_response(
    state: RunStateV1,
    artifact_root: Path,
) -> ArtifactListResponseV1:
    records = artifact_records(state)
    items = [
        _artifact_summary(state.run_id, record, artifact_root)
        for record in records
    ]
    return ArtifactListResponseV1(
        run_id=state.run_id,
        run_status=state.status,
        total=len(items),
        downloadable=sum(item.available for item in items),
        items=items,
    )


def artifact_records(state: RunStateV1) -> list[ArtifactRecord]:
    records: dict[str, ArtifactRecord] = {}
    for task in state.plan.tasks:
        record = state.task_records.get(str(task.task_id))
        if record is None or record.output is None:
            continue
        for ref in record.output.evidence_refs:
            artifact_id = artifact_id_for(ref.uri)
            records.setdefault(
                artifact_id,
                ArtifactRecord(
                    artifact_id=artifact_id,
                    ref=ref,
                    produced_by=record.agent_id,
                    task_id=record.task_id,
                ),
            )
    return list(records.values())


def artifact_id_for(uri: str) -> str:
    return hashlib.sha256(uri.encode("utf-8")).hexdigest()


def find_artifact_record(
    state: RunStateV1,
    artifact_id: str,
) -> ArtifactRecord | None:
    return next(
        (
            record
            for record in artifact_records(state)
            if record.artifact_id == artifact_id
        ),
        None,
    )


def resolve_local_artifact(
    run_id: UUID,
    record: ArtifactRecord,
    artifact_root: Path,
) -> Path | None:
    parts = urlsplit(record.ref.uri)
    layout = LOCAL_ARTIFACT_LAYOUT.get(parts.netloc)
    if parts.scheme != "artifact" or layout is None:
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) != 4:
        return None
    uri_run_id, uri_task_id, kind, filename = segments
    if (
        uri_run_id != str(run_id)
        or uri_task_id != str(record.task_id)
        or kind not in layout["kinds"]
        or Path(filename).name != filename
    ):
        return None

    root = artifact_root.resolve()
    candidate = (
        root
        / uri_run_id
        / uri_task_id
        / str(layout["directory"])
        / filename
    ).resolve()
    if not candidate.is_relative_to(root):
        return None
    return candidate


def artifact_integrity_matches(
    path: Path,
    expected_sha256: str | None,
) -> bool:
    if expected_sha256 is None:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected_sha256.lower()


def _artifact_summary(
    run_id: UUID,
    record: ArtifactRecord,
    artifact_root: Path,
) -> ArtifactSummaryV1:
    path = resolve_local_artifact(run_id, record, artifact_root)
    available = (
        path is not None
        and path.is_file()
        and record.ref.sha256 is not None
    )
    return ArtifactSummaryV1(
        artifact_id=record.artifact_id,
        uri=record.ref.uri,
        media_type=record.ref.media_type,
        sha256=record.ref.sha256,
        redacted=record.ref.redacted,
        description=record.ref.description,
        produced_by=record.produced_by,
        task_id=record.task_id,
        available=available,
        download_url=(
            f"/v1/runs/{run_id}/artifacts/{record.artifact_id}"
            if available
            else None
        ),
    )


def _report_findings(state: RunStateV1) -> list[CorrelatedFindingV1]:
    reporting_record = next(
        (
            record
            for record in state.task_records.values()
            if record.agent_id == "evidence_reporting_analyst"
            and record.output is not None
        ),
        None,
    )
    if reporting_record is None:
        return []
    report_value = reporting_record.output.output.get("report")
    if report_value is None:
        return []
    return QaRunReportV1.model_validate(report_value).findings
