"""Java language adapter.

Uses Maven (`mvn`) or Gradle (via the Gradle wrapper) to resolve dependencies.
Parses `pom.xml` directly without requiring `mvn` on PATH, so `required_tools`
is empty — the adapter activates purely on repo signal (presence of `pom.xml`
or `**/*.java` files).

`revapi` or `japicmp` are optional tools for API surface diffing.
ast-grep handles structural patching via `--lang java`.
"""

from __future__ import annotations

import re
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
    name="java",
    ecosystem="maven",
    display_name="Java",
    manifest_files=["pom.xml"],
    manifest_globs=["**/*.java"],
    exclude_dirs=["target", ".git", "node_modules", ".venv", "venv", "build"],
    required_tools=[],
    optional_tools=["mvn", "java", "gradle", "japicmp"],
    priority=55,
)

_POM_DEP_RE = re.compile(
    r"<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>"
    r"(?:\s*<version>([^<]*)</version>)?",
    re.DOTALL,
)
_JAVAC_DEPRECATION_RE = re.compile(r"^(.+\.java):(\d+): warning: \[deprecation\] (\S+) .+$", re.MULTILINE)


class JavaDependency:
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class JavaResolvedLockfile:
    def __init__(self, dependencies: list[Dependency]) -> None:
        self.dependencies = dependencies


class JavaDiff(BaseDiff):
    """Java AST-grep structural diff."""

    pass


class JavaDeprecationWarning:
    def __init__(self, symbol: str, message: str, file_path: Path, line: int) -> None:
        self.symbol = symbol
        self.message = message
        self.file_path = file_path
        self.line = line


class JavaAdapter:
    """Java language adapter. Parses Maven pom.xml without requiring mvn on PATH."""

    @property
    def ecosystem(self) -> str:
        return "maven"

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        pom_files = find_manifest_files(repo_path, ["pom.xml"], METADATA.exclude_dirs)
        if not pom_files:
            return []

        deps_by_name: dict[str, str] = {}
        for pom in pom_files:
            try:
                text = pom.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in _POM_DEP_RE.finditer(text):
                group, artifact = m.group(1).strip(), m.group(2).strip()
                version = (m.group(3) or "*").strip()
                coord = f"{group}:{artifact}"
                if coord not in deps_by_name or (deps_by_name[coord] == "*" and version != "*"):
                    deps_by_name[coord] = version

        return [JavaDependency(name=k, version=v) for k, v in sorted(deps_by_name.items())]

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        return JavaResolvedLockfile(dependencies=dependencies)

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        raise NotImplementedError(
            "Java API diffing requires japicmp or revapi. Install japicmp: https://siom79.github.io/japicmp/"
        )

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        """Generates a structural patch diff for record on file_path without modifying the file on disk."""
        return execute_structural_patch(file_path, record, language="java", diff_factory=JavaDiff)

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        """Parse javac -Xlint:deprecation output."""
        warnings: list[DeprecationWarning_] = []
        for m in _JAVAC_DEPRECATION_RE.finditer(test_run_output):
            warnings.append(
                JavaDeprecationWarning(
                    symbol=m.group(3),
                    message=f"deprecated usage at line {m.group(2)}",
                    file_path=Path(m.group(1)),
                    line=int(m.group(2)),
                )
            )
        return warnings


ADAPTER_CLASS = JavaAdapter
