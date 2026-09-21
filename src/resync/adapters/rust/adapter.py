from __future__ import annotations

import tomllib
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
    name="rust",
    ecosystem="crates",
    display_name="Rust",
    manifest_files=["Cargo.toml", "Cargo.lock"],
    manifest_globs=["**/*.rs"],
    exclude_dirs=["target", ".git", "node_modules"],
    required_tools=[],
    optional_tools=["cargo", "cargo-semver-checks", "rustc"],
    priority=80,
)


class RustDependency(Dependency):
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class RustResolvedLockfile(ResolvedLockfile):
    def __init__(self, dependencies: list[Dependency]) -> None:
        self.dependencies = dependencies


class RustDiff(BaseDiff):
    """Rust AST-grep structural diff."""

    pass


class RustAdapter(LanguageAdapter):
    """Rust language adapter using cargo/cargo-semver-checks/ast-grep with workspace support."""

    @property
    def ecosystem(self) -> str:
        return "crates"

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        cargo_files = find_manifest_files(repo_path, ["Cargo.toml"], METADATA.exclude_dirs)
        if not cargo_files:
            return []

        deps: list[Dependency] = []
        seen: set[str] = set()

        def _parse_deps(source: dict[str, str | dict[str, str]]) -> None:
            for name, spec in source.items():
                if name in seen:
                    continue
                version = "*"
                if isinstance(spec, str):
                    version = spec
                elif isinstance(spec, dict) and "version" in spec:
                    version = str(spec["version"])
                seen.add(name)
                deps.append(RustDependency(name=name, version=version))

        for cargo_file in cargo_files:
            try:
                with open(cargo_file, "rb") as f:
                    data = tomllib.load(f)
            except Exception:
                continue

            dependencies = data.get("dependencies", {})
            dev_dependencies = data.get("dev-dependencies", {})
            build_dependencies = data.get("build-dependencies", {})
            workspace_deps = data.get("workspace", {}).get("dependencies", {})

            if isinstance(dependencies, dict):
                _parse_deps(dependencies)
            if isinstance(dev_dependencies, dict):
                _parse_deps(dev_dependencies)
            if isinstance(build_dependencies, dict):
                _parse_deps(build_dependencies)
            if isinstance(workspace_deps, dict):
                _parse_deps(workspace_deps)

        return deps

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        return RustResolvedLockfile(dependencies=dependencies)

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        raise NotImplementedError("Requires shelling out to cargo-semver-checks")

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        """Generates a structural patch diff for record on file_path without modifying the file on disk."""
        return execute_structural_patch(file_path, record, language="rust", diff_factory=RustDiff)

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        return []


ADAPTER_CLASS = RustAdapter
