from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections import defaultdict
from pathlib import PurePosixPath
import re
import time

from adapters.github import GitHubInspectionV1, GitHubReadClient
from orchestrator.ports import AgentExecutionContextV1
from schemas.common import EvidenceRefV1, ObservationCertainty
from schemas.evidence import AgentOutputEnvelopeV1
from schemas.execution import SpecialistTaskV1
from schemas.project import (
    ChangeImpactMapV1,
    ImpactedSurfaceV1,
    ProjectCommandV1,
    ProjectComponentV1,
    ProjectProfileV1,
    PullRequestContextV1,
    RepositoryContextV1,
    RepositorySnapshotV1,
    RepositoryTargetV1,
    TechnologyDetectionV1,
)

from .models import RepositoryAnalysisOutputV1


LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
}
JS_FRAMEWORKS = {
    "next": "Next.js",
    "react": "React",
    "vue": "Vue",
    "@angular/core": "Angular",
    "express": "Express",
    "fastify": "Fastify",
    "nestjs": "NestJS",
    "@nestjs/core": "NestJS",
}
PYTHON_FRAMEWORKS = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
}
TEST_FRAMEWORKS = {
    "pytest": "pytest",
    "jest": "Jest",
    "vitest": "Vitest",
    "playwright": "Playwright",
    "@playwright/test": "Playwright",
    "cypress": "Cypress",
}
COMPONENT_MANIFEST_NAMES = {
    "package.json",
    "pyproject.toml",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "composer.json",
    "gemfile",
    "build.gradle",
    "build.gradle.kts",
}


class RepositoryAnalystExecutor:
    agent_id = "repository_analyst"

    def __init__(
        self,
        client: GitHubReadClient,
        *,
        reconnaissance_cache_seconds: float = 600.0,
    ) -> None:
        if reconnaissance_cache_seconds <= 0:
            raise ValueError("reconnaissance_cache_seconds must be positive")
        self.client = client
        self.reconnaissance_cache_seconds = reconnaissance_cache_seconds
        self._reconnaissance_cache: dict[
            tuple[str, str, bool, int | None],
            tuple[float, RepositoryAnalysisOutputV1],
        ] = {}
        self._reconnaissance_lock = asyncio.Lock()

    async def inspect_target(
        self,
        target: RepositoryTargetV1,
        pull_request_number: int | None = None,
    ) -> RepositoryAnalysisOutputV1:
        """Build a bounded read-only profile, briefly caching the approved snapshot."""

        key = (
            target.repository_id.casefold(),
            target.default_branch.casefold(),
            target.private,
            pull_request_number,
        )
        now = time.monotonic()
        cached = self._reconnaissance_cache.get(key)
        if cached is not None and now - cached[0] <= self.reconnaissance_cache_seconds:
            return cached[1].model_copy(deep=True)

        async with self._reconnaissance_lock:
            now = time.monotonic()
            cached = self._reconnaissance_cache.get(key)
            if cached is not None and now - cached[0] <= self.reconnaissance_cache_seconds:
                return cached[1].model_copy(deep=True)

            inspection = await self.client.inspect(target, pull_request_number)
            output = self._analyze(target, inspection)
            self._reconnaissance_cache = {
                cache_key: value
                for cache_key, value in self._reconnaissance_cache.items()
                if now - value[0] <= self.reconnaissance_cache_seconds
            }
            self._reconnaissance_cache[key] = (now, output)
            return output.model_copy(deep=True)

    async def execute(
        self,
        task: SpecialistTaskV1,
        context: AgentExecutionContextV1,
    ) -> AgentOutputEnvelopeV1:
        target = context.mission.repository_target
        if target is None:
            raise ValueError("repository_analyst requires a repository_target")
        output = await self.inspect_target(
            target,
            context.mission.pull_request_number,
        )
        evidence = _unique_evidence(output.repository_context.evidence_refs)
        return AgentOutputEnvelopeV1(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id,
            output_schema="RepositoryAnalysisOutputV1",
            output=output.model_dump(mode="json"),
            evidence_refs=evidence,
        )

    def _analyze(
        self,
        target: RepositoryTargetV1,
        inspection: GitHubInspectionV1,
    ) -> RepositoryAnalysisOutputV1:
        profile = _build_profile(target, inspection)
        pull = _pull_context(inspection)
        snapshot = RepositorySnapshotV1(
            repository_id=target.repository_id,
            commit_sha=inspection.commit_sha,
            root_tree_ref=inspection.tree_evidence_ref,
            file_count=len(inspection.tree_entries),
            total_bytes=sum(entry.size for entry in inspection.tree_entries),
            captured_paths=[item.path for item in inspection.captured_files],
            excluded_paths={
                **inspection.excluded_paths,
                **({"__tree__": "GitHub recursive tree response was truncated"} if inspection.tree_truncated else {}),
            },
        )
        evidence = [inspection.tree_evidence_ref]
        evidence.extend(item.evidence_ref for item in inspection.captured_files)
        if inspection.pull_request:
            evidence.append(inspection.pull_request.evidence_ref)
        context = RepositoryContextV1(
            target=target,
            snapshot=snapshot,
            pull_request=pull,
            profile=profile,
            evidence_refs=_unique_evidence(evidence),
        )
        return RepositoryAnalysisOutputV1(
            repository_context=context,
            project_profile=profile,
            change_impact=_impact_map(inspection, profile),
        )


def _build_profile(
    target: RepositoryTargetV1,
    inspection: GitHubInspectionV1,
) -> ProjectProfileV1:
    roots = _component_roots(inspection)
    components = [
        _build_component(root, roots, inspection)
        for root in roots
    ]
    unknowns: list[str] = []
    for component in components:
        if not component.frameworks:
            unknowns.append(
                f"No framework was confirmed for component {component.component_id}."
            )
        if not component.test_frameworks:
            unknowns.append(
                f"No test framework was confirmed for component {component.component_id}."
            )
    if inspection.tree_truncated:
        unknowns.append("GitHub truncated the recursive tree; repository coverage is partial.")
    language_names = {
        language.name
        for component in components
        for language in component.languages
        if language.name != "Unknown"
    }
    project_type = (
        "monorepo"
        if len(components) > 1
        else "polyglot"
        if len(language_names) > 1
        else "single_component"
    )
    return ProjectProfileV1(
        repository_id=target.repository_id,
        project_type=project_type,
        components=components,
        overall_confidence=0.9 if not inspection.tree_truncated else 0.75,
        unknowns=unknowns,
        evidence_refs=_unique_evidence(
            [inspection.tree_evidence_ref, *(item.evidence_ref for item in inspection.captured_files)]
        ),
    )


def _component_roots(inspection: GitHubInspectionV1) -> list[str]:
    roots: set[str] = set()
    for captured in inspection.captured_files:
        path = PurePosixPath(captured.path)
        basename = path.name.lower()
        if (
            basename in COMPONENT_MANIFEST_NAMES
            or basename.startswith("requirements") and basename.endswith(".txt")
            or basename.endswith(".csproj")
        ):
            parent = path.parent.as_posix()
            roots.add("." if parent == "." else parent)
    return sorted(roots or {"."}, key=lambda value: (value != ".", value))


def _build_component(
    root: str,
    roots: list[str],
    inspection: GitHubInspectionV1,
) -> ProjectComponentV1:
    tree_ref = inspection.tree_evidence_ref
    entries = [
        entry
        for entry in inspection.tree_entries
        if _owning_component_root(entry.path, roots) == root
    ]
    captured_files = [
        captured
        for captured in inspection.captured_files
        if _owning_component_root(captured.path, roots) == root
    ]
    language_counts = Counter(
        language
        for entry in entries
        if (language := LANGUAGES.get(PurePosixPath(entry.path).suffix.lower()))
    )
    languages = [
        _technology(name, tree_ref, confidence=0.95)
        for name, _ in language_counts.most_common()
    ]
    if not languages:
        languages = [
            _technology(
                "Unknown",
                tree_ref,
                confidence=0.2,
                certainty=ObservationCertainty.UNKNOWN,
            )
        ]

    frameworks: dict[str, TechnologyDetectionV1] = {}
    test_frameworks: dict[str, TechnologyDetectionV1] = {}
    package_managers: dict[str, TechnologyDetectionV1] = {}
    runtimes: dict[str, TechnologyDetectionV1] = {}
    commands: list[ProjectCommandV1] = []
    for captured in captured_files:
        basename = PurePosixPath(captured.path).name.lower()
        if basename == "package.json":
            package_managers["npm"] = _technology("npm", captured.evidence_ref)
            runtimes["Node.js"] = _technology("Node.js", captured.evidence_ref)
            _read_package_json(
                captured.content,
                captured.evidence_ref,
                frameworks,
                test_frameworks,
                commands,
                working_directory=root,
            )
        elif basename in {"pnpm-lock.yaml", "yarn.lock", "package-lock.json"}:
            manager = {"pnpm-lock.yaml": "pnpm", "yarn.lock": "Yarn"}.get(
                basename,
                "npm",
            )
            package_managers[manager] = _technology(manager, captured.evidence_ref)
        elif (
            basename in {"pyproject.toml", "poetry.lock", "pdm.lock", "uv.lock"}
            or basename.startswith("requirements")
        ):
            runtimes["Python"] = _technology("Python", captured.evidence_ref)
            manager = {
                "poetry.lock": "Poetry",
                "pdm.lock": "PDM",
                "uv.lock": "uv",
            }.get(basename, "pip")
            package_managers[manager] = _technology(manager, captured.evidence_ref)
            _read_python_dependencies(
                captured.content,
                captured.evidence_ref,
                frameworks,
                test_frameworks,
            )
        elif basename == "cargo.toml":
            package_managers["Cargo"] = _technology("Cargo", captured.evidence_ref)
            runtimes["Rust"] = _technology("Rust", captured.evidence_ref)
        elif basename == "go.mod":
            package_managers["Go modules"] = _technology(
                "Go modules",
                captured.evidence_ref,
            )
            runtimes["Go"] = _technology("Go", captured.evidence_ref)

    component_id = _component_id(root)
    return ProjectComponentV1(
        component_id=component_id,
        path=root,
        component_type=_component_type(root, set(frameworks)),
        languages=languages,
        frameworks=list(frameworks.values()),
        runtimes=list(runtimes.values()),
        package_managers=list(package_managers.values()),
        test_frameworks=list(test_frameworks.values()),
        commands=commands,
    )


def _owning_component_root(path: str, roots: list[str]) -> str:
    matches = [
        root
        for root in roots
        if root == "." or path == root or path.startswith(f"{root}/")
    ]
    if not matches:
        return "unmapped"
    return max(matches, key=lambda value: (value.count("/"), len(value)))


def _component_id(root: str) -> str:
    if root == ".":
        return "root"
    return re.sub(r"[^a-z0-9]+", "-", root.lower()).strip("-")


def _component_type(root: str, framework_names: set[str]) -> str:
    path_parts = {part.lower() for part in PurePosixPath(root).parts}
    if framework_names & {"Next.js", "React", "Vue", "Angular"}:
        return "frontend"
    if framework_names & {
        "FastAPI",
        "Django",
        "Flask",
        "Express",
        "Fastify",
        "NestJS",
    }:
        return "api"
    if path_parts & {"worker", "workers", "jobs", "consumers"}:
        return "worker"
    if path_parts & {"packages", "libs", "libraries"}:
        return "library"
    return "unknown"


def _read_package_json(
    content: str,
    evidence: EvidenceRefV1,
    frameworks: dict[str, TechnologyDetectionV1],
    test_frameworks: dict[str, TechnologyDetectionV1],
    commands: list[ProjectCommandV1],
    *,
    working_directory: str,
) -> None:
    try:
        package = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return
    dependencies = {
        **(package.get("dependencies") or {}),
        **(package.get("devDependencies") or {}),
    }
    for dependency in dependencies:
        if name := JS_FRAMEWORKS.get(dependency.lower()):
            frameworks[name] = _technology(name, evidence)
        if name := TEST_FRAMEWORKS.get(dependency.lower()):
            test_frameworks[name] = _technology(name, evidence)
    for name, command in (package.get("scripts") or {}).items():
        purpose = _script_purpose(name)
        if purpose and isinstance(command, str) and command.strip():
            commands.append(
                ProjectCommandV1(
                    purpose=purpose,
                    command=f"npm run {name}",
                    working_directory=working_directory,
                    source_ref=evidence,
                )
            )


def _read_python_dependencies(
    content: str,
    evidence: EvidenceRefV1,
    frameworks: dict[str, TechnologyDetectionV1],
    test_frameworks: dict[str, TechnologyDetectionV1],
) -> None:
    lowered = content.lower()
    for dependency, name in PYTHON_FRAMEWORKS.items():
        if dependency in lowered:
            frameworks[name] = _technology(name, evidence)
    for dependency, name in TEST_FRAMEWORKS.items():
        if dependency in lowered:
            test_frameworks[name] = _technology(name, evidence)


def _script_purpose(name: str) -> str | None:
    normalized = name.lower()
    for purpose in ("test", "build", "lint", "typecheck", "e2e", "start"):
        if normalized == purpose or normalized.startswith(f"{purpose}:"):
            return purpose
    return None


def _technology(
    name: str,
    evidence: EvidenceRefV1,
    *,
    confidence: float = 0.95,
    certainty: ObservationCertainty = ObservationCertainty.CONFIRMED,
) -> TechnologyDetectionV1:
    return TechnologyDetectionV1(
        name=name,
        certainty=certainty,
        confidence=confidence,
        evidence_refs=[evidence],
    )


def _pull_context(inspection: GitHubInspectionV1) -> PullRequestContextV1 | None:
    pull = inspection.pull_request
    if pull is None:
        return None
    return PullRequestContextV1(
        number=pull.number,
        base_sha=pull.base_sha,
        head_sha=pull.head_sha,
        base_branch=pull.base_branch,
        head_branch=pull.head_branch,
        title=pull.title,
        changed_files=[item.path for item in pull.files],
    )


def _impact_map(
    inspection: GitHubInspectionV1,
    profile: ProjectProfileV1,
) -> ChangeImpactMapV1 | None:
    pull = inspection.pull_request
    if pull is None or not pull.files:
        return None
    grouped_paths: dict[str, list[str]] = defaultdict(list)
    for item in pull.files:
        grouped_paths[_component_for_path(item.path, profile.components)].append(
            item.path
        )
    surfaces: list[ImpactedSurfaceV1] = []
    global_risk = "low"
    components_by_id = {
        component.component_id: component for component in profile.components
    }
    for component_id, paths in grouped_paths.items():
        risky = any(
            token in path.lower()
            for path in paths
            for token in (
                "auth",
                "payment",
                "checkout",
                "migration",
                "permission",
                "security",
            )
        )
        source_change = any(
            PurePosixPath(path).suffix.lower() in LANGUAGES for path in paths
        )
        risk = "high" if risky else "medium" if source_change else "low"
        if risk == "high":
            global_risk = "high"
        elif risk == "medium" and global_risk == "low":
            global_risk = "medium"
        hypotheses = [
            f"Changed files may alter behavior in component {component_id}."
        ]
        if risky:
            hypotheses.append(
                "Security-sensitive paths require focused verification."
            )
        user_journeys = _route_candidates(
            paths,
            components_by_id.get(component_id),
        )
        if user_journeys:
            hypotheses.append(
                "Framework file conventions identify candidate runtime journeys; "
                "they remain subject to the runtime allowlist."
            )
        surfaces.append(
            ImpactedSurfaceV1(
                surface_id=f"{component_id}-change",
                component_id=component_id,
                paths=paths,
                user_journeys=user_journeys,
                risk_hypotheses=hypotheses,
                confidence=0.9 if component_id != "unmapped" else 0.6,
                evidence_refs=[pull.evidence_ref],
            )
        )
    return ChangeImpactMapV1(
        change_id=f"github-pr:{pull.number}:{pull.head_sha}",
        impacted_surfaces=surfaces,
        global_risk=global_risk,
        evidence_refs=[pull.evidence_ref],
    )


def _component_for_path(
    path: str,
    components: list[ProjectComponentV1],
) -> str:
    matches = [
        component
        for component in components
        if component.path == "."
        or path == component.path
        or path.startswith(f"{component.path}/")
    ]
    if not matches:
        return "unmapped"
    return max(
        matches,
        key=lambda component: (
            component.path.count("/"),
            len(component.path),
        ),
    ).component_id


def _route_candidates(
    paths: list[str],
    component: ProjectComponentV1 | None,
) -> list[str]:
    if component is None or component.component_type != "frontend":
        return []
    candidates: set[str] = set()
    for path_value in paths:
        relative = path_value
        if component.path != ".":
            prefix = f"{component.path}/"
            if not path_value.startswith(prefix):
                continue
            relative = path_value[len(prefix):]
        parts = list(PurePosixPath(relative).parts)
        if parts and parts[0] == "src":
            parts = parts[1:]
        route_parts: list[str] | None = None
        if len(parts) >= 2 and parts[0] == "app" and parts[-1].split(".", 1)[0] == "page":
            route_parts = parts[1:-1]
        elif len(parts) >= 2 and parts[0] == "pages":
            filename = PurePosixPath(parts[-1]).stem
            if filename.startswith("_") or parts[1] == "api":
                continue
            route_parts = [*parts[1:-1], filename]
            if route_parts == ["index"]:
                route_parts = []
            elif route_parts and route_parts[-1] == "index":
                route_parts = route_parts[:-1]
        if route_parts is None:
            continue
        route_parts = [
            part
            for part in route_parts
            if not (part.startswith("(") and part.endswith(")"))
        ]
        if any("[" in part or "]" in part for part in route_parts):
            continue
        candidates.add("/" + "/".join(route_parts))
    return sorted(candidates)


def _unique_evidence(values: list[EvidenceRefV1]) -> list[EvidenceRefV1]:
    unique: dict[str, EvidenceRefV1] = {}
    for value in values:
        unique[value.uri] = value
    return list(unique.values())
