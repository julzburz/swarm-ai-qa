from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field

from schemas.common import NonEmptyStr, StrictModel, TaskStatus
from schemas.evidence import AgentOutputEnvelopeV1
from schemas.execution import SpecialistTaskV1
from schemas.mission import UserMissionRequestV1


class DependencyFailureV1(StrictModel):
    agent_id: NonEmptyStr
    status: TaskStatus
    error_class: NonEmptyStr | None = None
    error_message: NonEmptyStr | None = None


class AgentExecutionContextV1(StrictModel):
    run_id: UUID
    mission: UserMissionRequestV1
    attempt: int = Field(gt=0)
    dependency_outputs: dict[str, AgentOutputEnvelopeV1] = Field(default_factory=dict)
    dependency_failures: dict[str, DependencyFailureV1] = Field(
        default_factory=dict
    )


@runtime_checkable
class AgentExecutor(Protocol):
    agent_id: str

    async def execute(
        self,
        task: SpecialistTaskV1,
        context: AgentExecutionContextV1,
    ) -> AgentOutputEnvelopeV1:
        """Ejecuta una tarea acotada y devuelve un envelope validado."""
        ...
