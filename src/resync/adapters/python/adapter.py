from __future__ import annotations

import tomllib
from pathlib import Path

from resync.adapters.base import Dependency, DeprecationWarning_, Diff, LanguageAdapter, ResolvedLockfile
from resync.knowledge.schema import KnowledgeRecord


def _requirement_name(requirement: str) -> str:
    """Extracts the base package name from a PEP 508 requirement string."""
    stop = len(requirement)
    for i, char in enumerate(requirement):
        if char in ("=", "<", ">", "~", "!", ";", "[", "@"):
            stop = i
            break
    return requirement[:stop].strip()

class PythonDependency(Dependency):
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version

class PythonResolvedLockfile(ResolvedLockfile):
    def __init__(self, dependencies: list[Dependency]) -> None:
        self.dependencies = dependencies

class PythonDiff(Diff):
    def __init__(self, file_path: Path, old_text: str, new_text: str) -> None:
        self.file_path = file_path
        self.old_text = old_text
        self.new_text = new_text

class PythonAdapter(LanguageAdapter):
    """Python language adapter."""

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        pyproject_path = repo_path / "pyproject.toml"
        if not pyproject_path.exists():
            return []
        
        with pyproject_path.open("rb") as fh:
            data = tomllib.load(fh)

        project = data.get("project", {})
        requirements: list[str] = list(project.get("dependencies", []))
        for group_reqs in project.get("optional-dependencies", {}).values():
            requirements.extend(group_reqs)

        names = {_requirement_name(r) for r in requirements}
        return [PythonDependency(name=n, version="*") for n in sorted(names) if n]

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        from resync.adapters.python.resolver import resolve_dependencies
        return PythonResolvedLockfile(dependencies=resolve_dependencies(dependencies, target_profile))

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        from resync.adapters.python.extract_api_diff import extract
        return extract(package, version_old, version_new)

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        return PythonDiff(file_path=file_path, old_text="", new_text="")

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        return []
