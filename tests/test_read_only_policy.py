from __future__ import annotations

import pathlib
import unittest

import yaml

from schemas.specialists import (
    AccessibilityAgentOutputV1,
    BrowserAgentOutputV1,
    SecurityAgentOutputV1,
)


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReadOnlyProductPolicyTests(unittest.TestCase):
    def test_agent_profiles_do_not_allow_code_write_capabilities(self) -> None:
        prohibited = {
            "generate_unit_tests",
            "generate_playwright_test",
            "create_issue",
            "create_branch",
            "commit_patch",
            "open_pull_request",
            "modify_repository",
            "merge_pull_request",
            "deploy_release",
        }
        violations: list[str] = []
        for profile_path in (PROJECT_ROOT / "agents").glob("*.yaml"):
            if profile_path.name == "_profile_contract.yaml":
                continue
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            allowed = set(profile.get("allowed_capabilities", []))
            matches = sorted(allowed & prohibited)
            if matches:
                violations.append(f"{profile_path.name}: {matches}")
        self.assertEqual(violations, [])

    def test_browser_output_cannot_return_generated_code(self) -> None:
        fields = set(BrowserAgentOutputV1.model_fields)
        self.assertNotIn("generated_tests", fields)
        self.assertNotIn("patch", fields)
        self.assertNotIn("source_code", fields)

    def test_accessibility_output_cannot_return_generated_code(self) -> None:
        fields = set(AccessibilityAgentOutputV1.model_fields)
        self.assertNotIn("generated_tests", fields)
        self.assertNotIn("patch", fields)
        self.assertNotIn("source_code", fields)

    def test_security_output_cannot_return_generated_code(self) -> None:
        fields = set(SecurityAgentOutputV1.model_fields)
        self.assertNotIn("generated_tests", fields)
        self.assertNotIn("patch", fields)
        self.assertNotIn("source_code", fields)

    def test_prd_declares_permanent_read_only_boundary(self) -> None:
        prd = (PROJECT_ROOT / "Swarm_AI_QA_PRD_v1.0.md").read_text(encoding="utf-8")
        self.assertIn("permanentemente read-only respecto al código", prd)
        self.assertIn("nunca crea branches, commits, tests, fixes o pull requests", prd)


if __name__ == "__main__":
    unittest.main()
