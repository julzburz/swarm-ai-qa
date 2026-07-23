from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, func, select

from database.config import DatabaseSettings
from database.models import metadata, run_events, run_tasks, runs
from orchestrator.director import RuleBasedQaDirector
from orchestrator.engine import SwarmOrchestrator
from orchestrator.neon_store import NeonRunStore
from orchestrator.registry import AgentRegistry
from orchestrator.models import RunStatus
from schemas.common import MissionMode, QualityDomain
from schemas.evidence import AgentOutputEnvelopeV1
from schemas.mission import MissionJobV1, UserMissionRequestV1
from schemas.project import RepositoryTargetV1


class SuccessfulAgent:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id

    async def execute(self, task, context):
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema=f"{self.agent_id}.output.v1",
            output={"status": "ok"},
        )


def mission() -> UserMissionRequestV1:
    return UserMissionRequestV1(
        objective="Auditar seguridad del repositorio",
        mode=MissionMode.QUICK_TASK,
        repository_target=RepositoryTargetV1(
            repository_id="github:acme/shop",
            owner="acme",
            name="shop",
            clone_url="https://github.com/acme/shop.git",
        ),
        requested_jobs=[
            MissionJobV1(
                objective="Buscar problemas de seguridad",
                domains={QualityDomain.SECURITY},
            )
        ],
    )


class DatabaseConfigurationTests(unittest.TestCase):
    def test_neon_requires_pooled_application_and_direct_migration_urls(self) -> None:
        settings = DatabaseSettings(
            database_url=(
                "postgresql://user:secret@ep-swarm-pooler.us-east-2.aws.neon.tech/"
                "swarm?sslmode=require"
            ),
            database_direct_url=(
                "postgresql://user:secret@ep-swarm.us-east-2.aws.neon.tech/"
                "swarm?sslmode=require"
            ),
        )
        settings.validate_neon_topology()
        self.assertTrue(settings.is_neon)
        self.assertTrue(settings.uses_neon_pooler)
        self.assertFalse(settings.direct_url_uses_pooler)
        self.assertTrue(settings.sqlalchemy_url.startswith("postgresql+psycopg://"))
        self.assertNotIn("secret", repr(settings))

    def test_neon_rejects_pooler_url_for_migrations(self) -> None:
        settings = DatabaseSettings(
            database_url="postgresql://u:p@ep-a-pooler.us-east-2.aws.neon.tech/db",
            database_direct_url="postgresql://u:p@ep-a-pooler.us-east-2.aws.neon.tech/db",
        )
        with self.assertRaises(ValueError):
            settings.validate_neon_topology()

    def test_initial_metadata_contains_expected_tables(self) -> None:
        expected = {
            "projects",
            "repository_targets",
            "runtime_targets",
            "missions",
            "runs",
            "run_tasks",
            "run_events",
            "agent_messages",
            "tool_executions",
            "findings",
            "finding_verifications",
            "artifacts",
            "release_decisions",
        }
        self.assertEqual(set(metadata.tables), expected)


class NeonRunStoreCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_runs_against_relational_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "neon-emulation.db"
            engine = create_engine(f"sqlite+pysqlite:///{database_path}")
            store = NeonRunStore(engine=engine, create_schema=True)
            self.assertTrue(store.healthcheck())
            self.assertTrue(store.schema_is_ready())

            current_mission = mission()
            plan = RuleBasedQaDirector().build_plan(current_mission)
            registry = AgentRegistry()
            for agent_id in plan.selected_agents:
                registry.register(SuccessfulAgent(agent_id))
            orchestrator = SwarmOrchestrator(registry, store)

            state = await orchestrator.execute(current_mission, plan)
            self.assertEqual(state.status, RunStatus.COMPLETED)
            self.assertEqual(store.get_run(state.run_id).status, RunStatus.COMPLETED)
            self.assertGreater(len(store.list_events(state.run_id)), 0)

            with engine.connect() as connection:
                self.assertEqual(connection.execute(select(func.count()).select_from(runs)).scalar_one(), 1)
                self.assertEqual(
                    connection.execute(select(func.count()).select_from(run_tasks)).scalar_one(),
                    len(plan.tasks),
                )
                self.assertEqual(
                    connection.execute(select(func.count()).select_from(run_events)).scalar_one(),
                    len(store.list_events(state.run_id)),
                )
            run_id = state.run_id
            store.close()

            reopened_engine = create_engine(f"sqlite+pysqlite:///{database_path}")
            reopened = NeonRunStore(engine=reopened_engine)
            try:
                restored = reopened.get_run(run_id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.status, RunStatus.COMPLETED)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
