from __future__ import annotations

from typing import Literal
from uuid import UUID

from schemas.common import StrictModel
from schemas.mission import SwarmExecutionPlanV1, UserMissionRequestV1


class HealthResponseV1(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["swarm-ai-qa-control-plane"] = "swarm-ai-qa-control-plane"
    version: str
    storage: Literal["sqlite", "neon"]


class PlanPreviewResponseV1(StrictModel):
    mission: UserMissionRequestV1
    plan: SwarmExecutionPlanV1
    missing_executors: list[str]
    executable: bool


class CreateRunRequestV1(StrictModel):
    mission: UserMissionRequestV1
    approved: bool = False


class RunAcceptedResponseV1(StrictModel):
    run_id: UUID
    mission_id: UUID
    status: Literal["accepted"] = "accepted"
    plan: SwarmExecutionPlanV1
    state_url: str
    events_url: str
    event_stream_url: str
