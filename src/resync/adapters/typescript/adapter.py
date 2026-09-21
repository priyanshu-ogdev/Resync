from __future__ import annotations

import json
from pathlib import Path

from resync.adapters.base import (
    AdapterMetadata,
    BaseDiff,
    Dependency,
    DeprecationWarning_,
    Diff,
    LanguageAdapter,
    ResolvedLockfile,
    execute_structural_patch,
    find_manifest_files,
)
from resync.knowledge.schema import KnowledgeRecord

METADATA = AdapterMetadata(
    name="typescript",
    ecosystem="npm",
    display_name="TypeScript / JavaScript",
    manifest_files=["package.json"],
    manifest_globs=["**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx"],
    exclude_dirs=["node_modules", ".git", "dist", "build", ".venv", "venv"],
    required_tools=[],
    optional_tools=["npm", "yarn", "pnpm", "tsc", "node"],
    priority=75,
)


class TSDependency(Dependency):
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class TSResolvedLockfile(ResolvedLockfile):
    def __init__(self, dependencies: list[Dependency]) -> None:
        self.dependencies = dependencies


class TSDiff(BaseDiff):
    """TypeScript / JavaScript AST-grep structural diff."""

    pass


class TypeScriptAdapter(LanguageAdapter):
    """TypeScript language adapter using npm/tsc/ast-grep with workspace and monorepo support."""

    @property
    def ecosystem(self) -> str:
        return "npm"

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        manifest_paths = find_manifest_files(repo_path, ["package.json"], METADATA.exclude_dirs)
        if not manifest_paths:
            return []

        deps: list[Dependency] = []
        seen: set[str] = set()

        for pkg_path in manifest_paths:
            try:
                with open(pkg_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            all_deps: dict[str, str] = {}
            for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                val = data.get(key)
                if isinstance(val, dict):
                    all_deps.update({str(k): str(v) for k, v in val.items()})

            for name, version in all_deps.items():
                if name not in seen:
                    seen.add(name)
                    deps.append(TSDependency(name=name, version=version))

        return sorted(deps, key=lambda d: d.name)

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        return TSResolvedLockfile(dependencies=dependencies)

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        raise NotImplementedError("extract_api_diff requires TS Compiler API wrapper execution.")

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        """Generates a structural patch diff for record on file_path without modifying the file on disk."""
        # Detect whether file is TypeScript or JavaScript/TSX
        suffix = file_path.suffix.lower()
        lang = "tsx" if suffix == ".tsx" else ("typescript" if suffix in (".ts", ".mts", ".cts") else "javascript")
        return execute_structural_patch(file_path, record, language=lang, diff_factory=TSDiff)

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        return []


ADAPTER_CLASS = TypeScriptAdapter
