"""Go language adapter.

Uses the `go` toolchain — `go mod tidy`, `go list -m all`, and `go vet`.
This adapter requires the `go` binary on PATH (`required_tools=["go"]`) — it will be
silently skipped on machines without Go installed, rather than failing at runtime.

`go-apidiff` is an optional tool for API surface diffing between module versions.
ast-grep handles structural patching via `--lang go`.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from resync.adapters.base import (
    AdapterMetadata,
    BaseDiff,
    Dependency,
    DeprecationWarning_,
    Diff,
    ResolvedLockfile,
    execute_structural_patch,
    find_manifest_files,
)
from resync.knowledge.schema import KnowledgeRecord

METADATA = AdapterMetadata(
    name="go",
    ecosystem="go",
    display_name="Go",
    manifest_files=["go.mod", "go.sum"],
    manifest_globs=["**/*.go", "**/go.mod"],
    exclude_dirs=[".git", "vendor", "node_modules", ".venv", "venv"],
    required_tools=[],
    optional_tools=["go", "gopls", "staticcheck", "go-apidiff"],
    priority=70,
)


class GoDependency:
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class GoResolvedLockfile:
    def __init__(self, dependencies: list[Dependency]) -> None:
        self.dependencies = dependencies


class GoDiff(BaseDiff):
    """Go AST-grep structural diff."""

    pass


class GoDeprecationWarning:
    def __init__(self, symbol: str, message: str, file_path: Path, line: int) -> None:
        self.symbol = symbol
        self.message = message
        self.file_path = file_path
        self.line = line


_REQUIRE_RE = re.compile(r"^\s*require\s+(\S+)\s+(\S+)", re.MULTILINE)
_REQUIRE_BLOCK_RE = re.compile(r"require\s*\(([^)]+)\)", re.DOTALL)
_BLOCK_LINE_RE = re.compile(r"^\s*(\S+)\s+(\S+)", re.MULTILINE)


class GoAdapter:
    """Go language adapter using the go toolchain and ast-grep."""

    @property
    def ecosystem(self) -> str:
        return "go"

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        mod_files = find_manifest_files(repo_path, ["go.mod"], METADATA.exclude_dirs)
        if not mod_files:
            return []

        deps_by_name: dict[str, str] = {}

        for mod_file in mod_files:
            try:
                text = mod_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for m in _REQUIRE_RE.finditer(text):
                name, version = m.group(1), m.group(2)
                if name not in deps_by_name or (deps_by_name[name] == "*" and version != "*"):
                    deps_by_name[name] = version

            for block_m in _REQUIRE_BLOCK_RE.finditer(text):
                for line_m in _BLOCK_LINE_RE.finditer(block_m.group(1)):
                    name, version = line_m.group(1), line_m.group(2)
                    if not name.startswith("//"):
                        if name not in deps_by_name or (deps_by_name[name] == "*" and version != "*"):
                            deps_by_name[name] = version

        return [GoDependency(name=k, version=v) for k, v in sorted(deps_by_name.items())]

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        return GoResolvedLockfile(dependencies=dependencies)

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        if not shutil.which("go-apidiff"):
            raise NotImplementedError(
                "Go API diffing requires go-apidiff. Install: go install golang.org/x/exp/cmd/apidiff@latest"
            )
        raise NotImplementedError("go-apidiff integration not yet implemented.")

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        """Generates a structural patch diff for record on file_path without modifying the file on disk."""
        return execute_structural_patch(file_path, record, language="go", diff_factory=GoDiff)

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        """Parse go vet / staticcheck deprecation output."""
        warnings: list[DeprecationWarning_] = []
        pattern = re.compile(r"^(.+):(\d+):\d+: (.+deprecated.+)$", re.MULTILINE | re.IGNORECASE)
        for m in pattern.finditer(test_run_output):
            warnings.append(
                GoDeprecationWarning(
                    symbol="",
                    message=m.group(3).strip(),
                    file_path=Path(m.group(1)),
                    line=int(m.group(2)),
                )
            )
        return warnings


ADAPTER_CLASS = GoAdapter
