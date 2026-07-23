from __future__ import annotations

from .ports import AgentExecutor


class AgentRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, AgentExecutor] = {}

    def register(self, executor: AgentExecutor) -> None:
        agent_id = executor.agent_id.strip()
        if not agent_id:
            raise ValueError("agent_id cannot be empty")
        if agent_id in self._executors:
            raise ValueError(f"Agent already registered: {agent_id}")
        self._executors[agent_id] = executor

    def get(self, agent_id: str) -> AgentExecutor:
        try:
            return self._executors[agent_id]
        except KeyError as exc:
            raise LookupError(f"No executor registered for agent: {agent_id}") from exc

    def contains(self, agent_id: str) -> bool:
        return agent_id in self._executors

    @property
    def agent_ids(self) -> frozenset[str]:
        return frozenset(self._executors)

