from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from schemas.common import Environment, MissionMode, QualityDomain, RuntimeTargetV1, TaskStatus
from schemas.evidence import AgentOutputEnvelopeV1
from schemas.mission import MissionJobV1, UserMissionRequestV1
from schemas.project import RepositoryTargetV1
from orchestrator.director import RuleBasedQaDirector
from orchestrator.engine import SwarmOrchestrator
from orchestrator.events import EventStream
from orchestrator.models import RunEventType, RunStatus
from orchestrator.ports import AgentExecutionContextV1
from orchestrator.registry import AgentRegistry
from orchestrator.store import SQLiteRunStore


class ExecutionTracker:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.started: list[str] = []
        self.completed: list[str] = []


class FakeAgent:
    def __init__(
        self,
        agent_id: str,
        tracker: ExecutionTracker,
        delay: float = 0.005,
        failures_before_success: int = 0,
    ) -> None:
        self.agent_id = agent_id
        self.tracker = tracker
        self.delay = delay
        self.failures_before_success = failures_before_success
        self.calls = 0
        self.contexts: list[AgentExecutionContextV1] = []

    async def execute(self, task, context: AgentExecutionContextV1) -> AgentOutputEnvelopeV1:
        self.calls += 1
        self.contexts.append(context)
        self.tracker.active += 1
        self.tracker.max_active = max(self.tracker.max_active, self.tracker.active)
        self.tracker.started.append(self.agent_id)
        try:
            await asyncio.sleep(self.delay)
            if self.calls <= self.failures_before_success:
                raise RuntimeError(f"transient failure from {self.agent_id}")
            return AgentOutputEnvelopeV1(
                run_id=context.run_id,
                task_id=task.task_id,
                agent_id=self.agent_id,
                output_schema=f"{self.agent_id}.output.v1",
                output={
                    "status": "ok",
                    "dependency_count": len(context.dependency_outputs),
                },
            )
        finally:
            self.tracker.active -= 1
            self.tracker.completed.append(self.agent_id)


def runtime_mission() -> UserMissionRequestV1:
    return UserMissionRequestV1(
        objective="Examinar login y checkout",
        mode=MissionMode.TARGETED_EXAMINATION,
        runtime_target=RuntimeTargetV1(
            base_url="https://staging.example.com",
            environment=Environment.STAGING,
            allowed_paths=["/login", "/checkout"],
        ),
        selected_domains={
            QualityDomain.FUNCTIONAL,
            QualityDomain.SECURITY,
            QualityDomain.ACCESSIBILITY,
            QualityDomain.PERFORMANCE,
        },
        request_release_decision=True,
    )


def repository_mission() -> UserMissionRequestV1:
    return UserMissionRequestV1(
        objective="Revisar seguridad del PR",
        mode=MissionMode.QUICK_TASK,
        repository_target=RepositoryTargetV1(
            repository_id="github:acme/shop",
            owner="acme",
            name="shop",
            clone_url="https://github.com/acme/shop.git",
        ),
        pull_request_number=42,
        requested_jobs=[
            MissionJobV1(
                objective="Revisar vulnerabilidades",
                domains={QualityDomain.SECURITY},
            )
        ],
    )


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "runs.db"
        self.store = SQLiteRunStore(self.database_path)
        self.events = EventStream(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def registry_for_plan(self, plan, tracker: ExecutionTracker) -> AgentRegistry:
        registry = AgentRegistry()
        for agent_id in plan.selected_agents:
            registry.register(FakeAgent(agent_id, tracker))
        return registry

    async def test_executes_independent_specialists_in_parallel_then_fan_in(self) -> None:
        mission = runtime_mission()
        plan = RuleBasedQaDirector().build_plan(mission)
        tracker = ExecutionTracker()
        registry = self.registry_for_plan(plan, tracker)
        orchestrator = SwarmOrchestrator(registry, self.store, self.events)

        state = await orchestrator.execute(mission, plan)

        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertGreaterEqual(tracker.max_active, 2)
        self.assertTrue(
            all(record.status == TaskStatus.COMPLETED for record in state.task_records.values())
        )

        report_task = next(
            task for task in plan.tasks if task.agent_id == "evidence_reporting_analyst"
        )
        report_executor = registry.get("evidence_reporting_analyst")
        self.assertEqual(
            len(report_executor.contexts[-1].dependency_outputs),
            len(report_task.depends_on),
        )

        release_executor = registry.get("release_manager")
        self.assertEqual(len(release_executor.contexts[-1].dependency_outputs), 1)

    async def test_retries_transient_agent_failure(self) -> None:
        mission = repository_mission()
        plan = RuleBasedQaDirector().build_plan(mission)
        tracker = ExecutionTracker()
        registry = AgentRegistry()
        for agent_id in plan.selected_agents:
            failures = 1 if agent_id == "security_test_engineer" else 0
            registry.register(
                FakeAgent(agent_id, tracker, failures_before_success=failures)
            )
        orchestrator = SwarmOrchestrator(
            registry,
            self.store,
            self.events,
            max_retries=1,
        )

        state = await orchestrator.execute(mission, plan)

        self.assertEqual(state.status, RunStatus.COMPLETED)
        security = registry.get("security_test_engineer")
        self.assertEqual(security.calls, 2)
        events = self.store.list_events(state.run_id)
        self.assertTrue(
            any(event.event_type == RunEventType.AGENT_RETRYING for event in events)
        )

    async def test_failed_dependency_still_produces_partial_report(self) -> None:
        mission = repository_mission()
        plan = RuleBasedQaDirector().build_plan(mission)
        tracker = ExecutionTracker()
        registry = AgentRegistry()
        for agent_id in plan.selected_agents:
            failures = 10 if agent_id == "repository_analyst" else 0
            registry.register(
                FakeAgent(agent_id, tracker, failures_before_success=failures)
            )
        orchestrator = SwarmOrchestrator(
            registry,
            self.store,
            self.events,
            max_retries=1,
        )

        state = await orchestrator.execute(mission, plan)

        self.assertEqual(
            state.status,
            RunStatus.COMPLETED_WITH_WARNINGS,
        )
        self.assertEqual(
            next(
                record
                for record in state.task_records.values()
                if record.agent_id == "repository_analyst"
            ).status,
            TaskStatus.FAILED,
        )
        self.assertEqual(
            next(
                record
                for record in state.task_records.values()
                if record.agent_id == "test_architect"
            ).status,
            TaskStatus.SKIPPED,
        )
        self.assertEqual(
            next(
                record
                for record in state.task_records.values()
                if record.agent_id == "evidence_reporting_analyst"
            ).status,
            TaskStatus.COMPLETED,
        )

    async def test_events_and_final_state_survive_store_reopen(self) -> None:
        mission = repository_mission()
        plan = RuleBasedQaDirector().build_plan(mission)
        tracker = ExecutionTracker()
        registry = self.registry_for_plan(plan, tracker)
        orchestrator = SwarmOrchestrator(registry, self.store, self.events)

        state = await orchestrator.execute(mission, plan)
        run_id = state.run_id
        event_count = len(self.store.list_events(run_id))
        self.store.close()

        reopened = SQLiteRunStore(self.database_path)
        try:
            restored = reopened.get_run(run_id)
            self.assertIsNotNone(restored)
            self.assertEqual(restored.status, RunStatus.COMPLETED)
            restored_events = reopened.list_events(run_id)
            self.assertEqual(len(restored_events), event_count)
            self.assertEqual(restored_events[-1].event_type, RunEventType.RUN_COMPLETED)
        finally:
            reopened.close()
        self.store = SQLiteRunStore(self.database_path)

    async def test_missing_executor_is_rejected_before_run(self) -> None:
        mission = repository_mission()
        plan = RuleBasedQaDirector().build_plan(mission)
        registry = AgentRegistry()
        orchestrator = SwarmOrchestrator(registry, self.store, self.events)

        with self.assertRaises(LookupError):
            await orchestrator.execute(mission, plan)

    async def test_known_run_id_supports_live_cancellation(self) -> None:
        mission = runtime_mission()
        plan = RuleBasedQaDirector().build_plan(mission)
        tracker = ExecutionTracker()
        registry = AgentRegistry()
        for agent_id in plan.selected_agents:
            registry.register(FakeAgent(agent_id, tracker, delay=1.0))
        orchestrator = SwarmOrchestrator(registry, self.store, self.events)
        run_id = uuid4()

        execution = asyncio.create_task(
            orchestrator.execute(mission, plan, run_id=run_id)
        )
        while self.store.get_run(run_id) is None:
            await asyncio.sleep(0.001)
        await orchestrator.cancel(run_id)
        state = await asyncio.wait_for(execution, timeout=0.5)

        self.assertEqual(state.run_id, run_id)
        self.assertEqual(state.status, RunStatus.CANCELLED)
        self.assertTrue(state.cancellation_requested)
        self.assertTrue(
            all(
                record.status == TaskStatus.CANCELLED
                for record in state.task_records.values()
            )
        )
        self.assertEqual(
            self.store.list_events(run_id)[-1].event_type,
            RunEventType.RUN_CANCELLED,
        )

    async def test_live_event_subscription_receives_ordered_terminal_stream(self) -> None:
        mission = repository_mission()
        plan = RuleBasedQaDirector().build_plan(mission)
        tracker = ExecutionTracker()
        registry = self.registry_for_plan(plan, tracker)
        orchestrator = SwarmOrchestrator(registry, self.store, self.events)
        run_id = uuid4()

        async def collect_events():
            return [event async for event in self.events.subscribe(run_id)]

        collector = asyncio.create_task(collect_events())
        await asyncio.sleep(0)
        state = await orchestrator.execute(mission, plan, run_id=run_id)
        received = await asyncio.wait_for(collector, timeout=0.5)

        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(received[0].event_type, RunEventType.RUN_CREATED)
        self.assertEqual(received[-1].event_type, RunEventType.RUN_COMPLETED)
        sequences = [event.sequence for event in received]
        self.assertEqual(sequences, sorted(sequences))


class QaDirectorTests(unittest.TestCase):
    def test_production_plan_includes_restrictions(self) -> None:
        mission = UserMissionRequestV1(
            objective="Auditar release en producción",
            mode=MissionMode.FULL_EXAMINATION,
            runtime_target=RuntimeTargetV1(
                base_url="https://example.com",
                environment=Environment.PRODUCTION,
                allowed_paths=["/", "/login"],
            ),
        )
        plan = RuleBasedQaDirector().build_plan(mission)

        self.assertTrue(plan.production_restrictions)
        self.assertIn("release_manager", plan.selected_agents)
        self.assertNotIn("chaos_resilience_engineer", plan.selected_agents)

    def test_repo_only_plan_does_not_select_browser_domains(self) -> None:
        mission = repository_mission()
        plan = RuleBasedQaDirector().build_plan(mission)

        self.assertIn("security_test_engineer", plan.selected_agents)
        self.assertNotIn("browser_automation_engineer", plan.selected_agents)
        self.assertNotIn("api_test_engineer", plan.selected_agents)
        self.assertNotIn("accessibility_specialist", plan.selected_agents)


if __name__ == "__main__":
    unittest.main()
