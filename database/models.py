from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB


metadata = MetaData()
json_type = JSON().with_variant(JSONB(), "postgresql")
sequence_type = BigInteger().with_variant(Integer(), "sqlite")


projects = Table(
    "projects",
    metadata,
    Column("project_id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

repository_targets = Table(
    "repository_targets",
    metadata,
    Column("target_id", Uuid(as_uuid=True), primary_key=True),
    Column("project_id", Uuid(as_uuid=True), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=True),
    Column("provider", String(50), nullable=False, server_default="github"),
    Column("repository_id", String(500), nullable=False),
    Column("owner", String(200), nullable=False),
    Column("name", String(200), nullable=False),
    Column("default_branch", String(300), nullable=False, server_default="main"),
    Column("is_private", Boolean, nullable=False, server_default=text("false")),
    Column("configuration", json_type, nullable=False, server_default=text("'{}'")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("provider", "repository_id", name="uq_repository_target_provider_id"),
)

runtime_targets = Table(
    "runtime_targets",
    metadata,
    Column("target_id", Uuid(as_uuid=True), primary_key=True),
    Column("project_id", Uuid(as_uuid=True), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=True),
    Column("base_url", Text, nullable=False),
    Column("environment", String(30), nullable=False),
    Column("allowed_paths", json_type, nullable=False),
    Column("blocked_paths", json_type, nullable=False),
    Column("test_account_secret_ref", Text, nullable=True),
    Column("configuration", json_type, nullable=False, server_default=text("'{}'")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "environment IN ('local','sandbox','staging','production')",
        name="ck_runtime_target_environment",
    ),
)

missions = Table(
    "missions",
    metadata,
    Column("mission_id", Uuid(as_uuid=True), primary_key=True),
    Column("project_id", Uuid(as_uuid=True), ForeignKey("projects.project_id", ondelete="SET NULL"), nullable=True),
    Column("mode", String(40), nullable=False),
    Column("objective", Text, nullable=False),
    Column("request_json", json_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

runs = Table(
    "runs",
    metadata,
    Column("run_id", Uuid(as_uuid=True), primary_key=True),
    Column("mission_id", Uuid(as_uuid=True), nullable=False),
    Column("status", String(40), nullable=False),
    Column("state_json", json_type, nullable=False),
    Column("error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

run_tasks = Table(
    "run_tasks",
    metadata,
    Column("task_id", Uuid(as_uuid=True), primary_key=True),
    Column("run_id", Uuid(as_uuid=True), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("agent_id", String(200), nullable=False),
    Column("status", String(40), nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("record_json", json_type, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

run_events = Table(
    "run_events",
    metadata,
    Column("sequence", sequence_type, primary_key=True, autoincrement=True),
    Column("event_id", Uuid(as_uuid=True), nullable=False, unique=True),
    Column("run_id", Uuid(as_uuid=True), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("event_type", String(100), nullable=False),
    Column("agent_id", String(200), nullable=True),
    Column("task_id", Uuid(as_uuid=True), nullable=True),
    Column("event_json", json_type, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)
Index("idx_run_events_run_sequence", run_events.c.run_id, run_events.c.sequence)

agent_messages = Table(
    "agent_messages",
    metadata,
    Column("message_id", Uuid(as_uuid=True), primary_key=True),
    Column("run_id", Uuid(as_uuid=True), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("from_agent", String(200), nullable=False),
    Column("to_agent", String(200), nullable=False),
    Column("intent", String(100), nullable=False),
    Column("message_json", json_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

tool_executions = Table(
    "tool_executions",
    metadata,
    Column("execution_id", Uuid(as_uuid=True), primary_key=True),
    Column("run_id", Uuid(as_uuid=True), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("task_id", Uuid(as_uuid=True), nullable=False),
    Column("capability_id", String(200), nullable=False),
    Column("tool_name", String(200), nullable=False),
    Column("tool_version", String(100), nullable=False),
    Column("status", String(50), nullable=False),
    Column("result_json", json_type, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=False),
)

findings = Table(
    "findings",
    metadata,
    Column("finding_id", Uuid(as_uuid=True), primary_key=True),
    Column("run_id", Uuid(as_uuid=True), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("task_id", Uuid(as_uuid=True), nullable=False),
    Column("reported_by", String(200), nullable=False),
    Column("domain", String(50), nullable=False),
    Column("severity", String(20), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("title", Text, nullable=False),
    Column("verification_status", String(30), nullable=False),
    Column("finding_json", json_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_finding_confidence"),
)
Index("idx_findings_run_severity", findings.c.run_id, findings.c.severity)

finding_verifications = Table(
    "finding_verifications",
    metadata,
    Column("verification_id", Uuid(as_uuid=True), primary_key=True),
    Column("finding_id", Uuid(as_uuid=True), ForeignKey("findings.finding_id", ondelete="CASCADE"), nullable=False),
    Column("responder_agent", String(200), nullable=False),
    Column("status", String(30), nullable=False),
    Column("verification_json", json_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("artifact_id", Uuid(as_uuid=True), primary_key=True),
    Column("run_id", Uuid(as_uuid=True), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("task_id", Uuid(as_uuid=True), nullable=True),
    Column("artifact_uri", Text, nullable=False),
    Column("media_type", String(200), nullable=False),
    Column("sha256", String(64), nullable=True),
    Column("storage_key", Text, nullable=False),
    Column("redacted", Boolean, nullable=False, server_default=text("false")),
    Column("metadata_json", json_type, nullable=False, server_default=text("'{}'")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("run_id", "artifact_uri", name="uq_artifact_run_uri"),
)

release_decisions = Table(
    "release_decisions",
    metadata,
    Column("decision_id", Uuid(as_uuid=True), primary_key=True),
    Column("run_id", Uuid(as_uuid=True), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("decision", String(30), nullable=False),
    Column("score", Float, nullable=False),
    Column("decision_json", json_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("score >= 0 AND score <= 100", name="ck_release_score"),
)

