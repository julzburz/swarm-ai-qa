from __future__ import annotations

import unittest
from uuid import uuid4

from pydantic import ValidationError

from schemas.common import (
    Environment,
    EvidenceRefV1,
    MissionMode,
    ObservationCertainty,
    QualityDomain,
    RuntimeTargetV1,
    Severity,
)
from schemas.evidence import FindingV1
from schemas.execution import CoverageObjectiveV1, SpecialistTaskV1, TestPlanV1
from schemas.mission import MissionJobV1, UserMissionRequestV1
from schemas.project import (
    ProjectComponentV1,
    ProjectProfileV1,
    RepositoryTargetV1,
    TechnologyDetectionV1,
)
from schemas.release import (
    GateResultV1,
    ReleaseConfidenceBreakdownV1,
    ReleaseDecisionV1,
    ScoreComponentV1,
)
from schemas.common import BudgetV1


def evidence(name: str = "result.json") -> EvidenceRefV1:
    return EvidenceRefV1(
        uri=f"artifact://test/{name}",
        media_type="application/json",
        sha256="a" * 64,
    )


def repository() -> RepositoryTargetV1:
    return RepositoryTargetV1(
        repository_id="github:acme/shop",
        owner="acme",
        name="shop",
        clone_url="https://github.com/acme/shop.git",
    )


class MissionContractTests(unittest.TestCase):
    def test_quick_task_accepts_one_or_two_jobs(self) -> None:
        request = UserMissionRequestV1(
            objective="Revisar seguridad y verificar login",
            mode=MissionMode.QUICK_TASK,
            repository_target=repository(),
            requested_jobs=[
                MissionJobV1(objective="Revisar seguridad", domains={QualityDomain.SECURITY}),
                MissionJobV1(objective="Verificar login", domains={QualityDomain.FUNCTIONAL}),
            ],
        )
        self.assertEqual(len(request.requested_jobs), 2)

    def test_quick_task_rejects_three_jobs(self) -> None:
        with self.assertRaises(ValidationError):
            UserMissionRequestV1(
                objective="Demasiados trabajos",
                mode=MissionMode.QUICK_TASK,
                repository_target=repository(),
                requested_jobs=[
                    MissionJobV1(objective=f"Trabajo {index}", domains={QualityDomain.FUNCTIONAL})
                    for index in range(3)
                ],
            )

    def test_production_rejects_load_and_chaos(self) -> None:
        with self.assertRaises(ValidationError):
            RuntimeTargetV1(
                base_url="https://example.com",
                environment=Environment.PRODUCTION,
                allow_load_testing=True,
            )

    def test_runtime_target_rejects_internal_and_metadata_addresses(self) -> None:
        for unsafe_url in (
            "http://127.0.0.1:8000",
            "http://10.0.0.5",
            "http://169.254.169.254/latest/meta-data",
            "http://localhost:3000",
        ):
            with self.subTest(unsafe_url=unsafe_url), self.assertRaises(ValidationError):
                RuntimeTargetV1(
                    base_url=unsafe_url,
                    environment=Environment.STAGING,
                )


class ProjectIntelligenceContractTests(unittest.TestCase):
    def test_repository_target_requires_matching_canonical_identifiers(self) -> None:
        invalid_targets = [
            {
                "repository_id": "github:acme/shop",
                "owner": "../../user",
                "name": "shop",
                "clone_url": "https://github.com/acme/shop.git",
            },
            {
                "repository_id": "github:other/shop",
                "owner": "acme",
                "name": "shop",
                "clone_url": "https://github.com/acme/shop.git",
            },
            {
                "repository_id": "github:acme/shop",
                "owner": "acme",
                "name": "shop",
                "clone_url": "https://github.com/other/repository.git",
            },
        ]
        for target in invalid_targets:
            with self.subTest(target=target), self.assertRaises(ValidationError):
                RepositoryTargetV1(**target)

    def test_confirmed_technology_requires_high_confidence(self) -> None:
        with self.assertRaises(ValidationError):
            TechnologyDetectionV1(
                name="Next.js",
                certainty=ObservationCertainty.CONFIRMED,
                confidence=0.70,
                evidence_refs=[evidence("package.json")],
            )

    def test_polyglot_profile_keeps_components_separate(self) -> None:
        typescript = TechnologyDetectionV1(
            name="TypeScript",
            certainty=ObservationCertainty.CONFIRMED,
            confidence=0.99,
            evidence_refs=[evidence("web-package.json")],
        )
        python = TechnologyDetectionV1(
            name="Python",
            certainty=ObservationCertainty.CONFIRMED,
            confidence=0.99,
            evidence_refs=[evidence("pyproject.toml")],
        )
        profile = ProjectProfileV1(
            repository_id="github:acme/shop",
            project_type="polyglot",
            components=[
                ProjectComponentV1(
                    component_id="web",
                    path="apps/web",
                    component_type="frontend",
                    languages=[typescript],
                ),
                ProjectComponentV1(
                    component_id="api",
                    path="services/api",
                    component_type="api",
                    languages=[python],
                ),
            ],
            overall_confidence=0.98,
        )
        self.assertEqual({item.component_id for item in profile.components}, {"web", "api"})


class EvidenceContractTests(unittest.TestCase):
    def test_critical_finding_rejects_low_confidence(self) -> None:
        with self.assertRaises(ValidationError):
            FindingV1(
                run_id=uuid4(),
                task_id=uuid4(),
                reported_by="security_test_engineer",
                domain=QualityDomain.SECURITY,
                title="Exposición crítica",
                severity=Severity.CRITICAL,
                confidence=0.60,
                observation="El scanner produjo una señal sin verificar.",
                impact="Posible compromiso.",
                reproduction_steps=["Ejecutar el scanner autorizado."],
                evidence_refs=[evidence()],
                recommendation="Verificar manualmente.",
            )

    def test_confirmed_finding_requires_independent_verifier(self) -> None:
        finding = FindingV1(
            run_id=uuid4(),
            task_id=uuid4(),
            reported_by="security_test_engineer",
            domain=QualityDomain.SECURITY,
            title="Cookie sin SameSite",
            severity=Severity.HIGH,
            confidence=0.96,
            observation="Set-Cookie no contiene SameSite.",
            impact="Aumenta la exposición a solicitudes cross-site.",
            reproduction_steps=["Iniciar sesión.", "Inspeccionar Set-Cookie."],
            evidence_refs=[evidence("login-response.json")],
            recommendation="Configurar SameSite=Lax o Strict.",
            verified_by=["browser_automation_engineer"],
            verification_status="confirmed",
        )
        self.assertEqual(finding.verification_status, "confirmed")


class PlanningAndReleaseContractTests(unittest.TestCase):
    def test_plan_rejects_request_budget_overflow(self) -> None:
        task = SpecialistTaskV1(
            agent_id="browser_automation_engineer",
            objective="Probar login",
            domain=QualityDomain.FUNCTIONAL,
            capability_ids=["navigate_flow"],
            risk_refs=["risk:login"],
            estimated_requests=11,
        )
        with self.assertRaises(ValidationError):
            TestPlanV1(
                mission_id=uuid4(),
                strategy_summary="Validar el flujo afectado.",
                coverage_objectives=[
                    CoverageObjectiveV1(
                        objective_id="login",
                        domain=QualityDomain.FUNCTIONAL,
                        risk_reference="risk:login",
                        description="Login funciona.",
                        acceptance_criteria=["El usuario accede al dashboard."],
                    )
                ],
                tasks=[task],
                budget=BudgetV1(max_requests=10),
            )

    def test_blocking_gate_forces_blocked_decision(self) -> None:
        score = ReleaseConfidenceBreakdownV1(
            components=[
                ScoreComponentV1(
                    domain=QualityDomain.SECURITY,
                    score=95,
                    weight=1,
                    explanation="Resultado ponderado de seguridad.",
                    evidence_refs=[evidence("score.json")],
                )
            ],
            evidence_completeness=1,
            tool_reliability=1,
            total_score=95,
        )
        gate = GateResultV1(
            gate_id="no-critical",
            status="failed",
            blocking=True,
            explanation="Existe un hallazgo crítico verificado.",
            policy_ref="release-policy@1",
            evidence_refs=[evidence("gate.json")],
        )
        with self.assertRaises(ValidationError):
            ReleaseDecisionV1(
                run_id=uuid4(),
                decision="ready",
                score=score,
                gate_results=[gate],
                summary="No debe aprobarse.",
            )

    def test_core_models_export_json_schema(self) -> None:
        for model in (UserMissionRequestV1, ProjectProfileV1, TestPlanV1, FindingV1, ReleaseDecisionV1):
            generated = model.model_json_schema()
            self.assertEqual(generated["type"], "object")


if __name__ == "__main__":
    unittest.main()
