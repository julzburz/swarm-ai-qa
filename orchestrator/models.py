from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from schemas.common import NonEmptyStr, StrictModel, TaskStatus
from schemas.evidence import AgentOutputEnvelopeV1
from schemas.mission import SwarmExecutionPlanV1, UserMissionRequestV1


class RunStatus(StrEnum):
    CREATED = "created"
    PLANNED = "planned"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunEventType(StrEnum):
    RUN_CREATED = "run.created"
    RUN_PLANNED = "run.planned"
    RUN_STARTED = "run.started"
    RUN_CANCELLATION_REQUESTED = "run.cancellation_requested"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    AGENT_STARTED = "agent.started"
    AGENT_RETRYING = "agent.retrying"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    AGENT_SKIPPED = "agent.skipped"


class RunEventV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID = Field(default_factory=uuid4)
    sequence: int | None = Field(default=None, gt=0)
    run_id: UUID
    event_type: RunEventType
    agent_id: NonEmptyStr | None = None
    task_id: UUID | None = None
    message: NonEmptyStr
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskExecutionRecordV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    task_id: UUID
    agent_id: NonEmptyStr
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = Field(ge=0, default=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output: AgentOutputEnvelopeV1 | None = None
    error_class: NonEmptyStr | None = None
    error_message: NonEmptyStr | None = None

    @model_validator(mode="after")
    def terminal_record_is_consistent(self) -> "TaskExecutionRecordV1":
        if self.status == TaskStatus.COMPLETED and self.output is None:
            raise ValueError("Completed task requires output")
        if self.status == TaskStatus.FAILED and self.error_class is None:
            raise ValueError("Failed task requires error_class")
        return self


class RunStateV1(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID = Field(default_factory=uuid4)
    mission: UserMissionRequestV1
    plan: SwarmExecutionPlanV1
    status: RunStatus = RunStatus.CREATED
    task_records: dict[str, TaskExecutionRecordV1]
    cancellation_requested: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: NonEmptyStr | None = None

    @model_validator(mode="after")
    def records_match_plan(self) -> "RunStateV1":
        planned = {str(task.task_id): task.agent_id for task in self.plan.tasks}
        actual = {key: value.agent_id for key, value in self.task_records.items()}
        if planned != actual:
            raise ValueError("task_records must match every task in the execution plan")
        if self.plan.mission_id != self.mission.mission_id:
            raise ValueError("Plan and mission IDs must match")
        return self

