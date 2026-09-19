from __future__ import annotations

import tomllib
from pathlib import Path

from resync.adapters.base import Dependency, DeprecationWarning_, Diff, LanguageAdapter, ResolvedLockfile
from resync.knowledge.schema import KnowledgeRecord


class RustDependency(Dependency):
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class RustResolvedLockfile(ResolvedLockfile):
    def __init__(self, dependencies: list[Dependency]) -> None:
        self.dependencies = dependencies


class RustDiff(Diff):
    def __init__(self, file_path: Path, old_text: str, new_text: str) -> None:
        self.file_path = file_path
        self.old_text = old_text
        self.new_text = new_text


class RustAdapter(LanguageAdapter):
    """Rust language adapter using cargo/cargo-semver-checks/ast-grep."""

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        cargo_toml = repo_path / "Cargo.toml"
        if not cargo_toml.exists():
            return []

        with open(cargo_toml, "rb") as f:
            data = tomllib.load(f)

        deps: list[Dependency] = []
        dependencies = data.get("dependencies", {})
        dev_dependencies = data.get("dev-dependencies", {})

        def _parse_deps(source: dict[str, str | dict[str, str]]) -> None:
            for name, spec in source.items():
                if isinstance(spec, str):
                    deps.append(RustDependency(name=name, version=spec))
                elif isinstance(spec, dict) and "version" in spec:
                    deps.append(RustDependency(name=name, version=spec["version"]))

        _parse_deps(dependencies)
        _parse_deps(dev_dependencies)

        return deps

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        return RustResolvedLockfile(dependencies=dependencies)

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        raise NotImplementedError("Requires shelling out to cargo-semver-checks")

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        return RustDiff(file_path=file_path, old_text="", new_text="")

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        return []
