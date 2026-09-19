from __future__ import annotations

import json
from pathlib import Path

from resync.adapters.base import Dependency, DeprecationWarning_, Diff, LanguageAdapter, ResolvedLockfile
from resync.knowledge.schema import KnowledgeRecord


class TSDependency(Dependency):
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class TSResolvedLockfile(ResolvedLockfile):
    def __init__(self, dependencies: list[Dependency]) -> None:
        self.dependencies = dependencies


class TSDiff(Diff):
    def __init__(self, file_path: Path, old_text: str, new_text: str) -> None:
        self.file_path = file_path
        self.old_text = old_text
        self.new_text = new_text


class TypeScriptAdapter(LanguageAdapter):
    """TypeScript language adapter using npm/tsc/ast-grep."""

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        package_json = repo_path / "package.json"
        if not package_json.exists():
            return []

        with open(package_json, encoding="utf-8") as f:
            data = json.load(f)

        deps: list[Dependency] = []
        dependencies = data.get("dependencies", {})
        dev_dependencies = data.get("devDependencies", {})

        for name, version in dependencies.items():
            deps.append(TSDependency(name=str(name), version=str(version)))
        for name, version in dev_dependencies.items():
            deps.append(TSDependency(name=str(name), version=str(version)))

        return deps

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        return TSResolvedLockfile(dependencies=dependencies)

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        raise NotImplementedError("extract_api_diff requires TS Compiler API wrapper execution.")

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        return TSDiff(file_path=file_path, old_text="", new_text="")

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        return []
