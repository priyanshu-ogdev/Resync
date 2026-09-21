from __future__ import annotations

import re
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
    name="python",
    ecosystem="pypi",
    display_name="Python",
    manifest_files=["pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile"],
    manifest_globs=["**/*.py"],
    exclude_dirs=[".venv", "venv", ".git", "__pycache__", "dist", "build", "node_modules"],
    required_tools=[],
    optional_tools=["uv", "pip", "poetry"],
    priority=100,
)

_SETUP_REQUIRES_RE = re.compile(r"""install_requires\s*=\s*\[([^\]]+)\]""", re.DOTALL)
_SETUP_CFG_REQ_RE = re.compile(r"""(?:install_requires|dependencies)\s*=\s*\n((?:\s+[^\n]+\n)+)""")


def _requirement_name(requirement: str) -> str:
    """Extracts the base package name from a PEP 508 requirement string."""
    if " --" in requirement:
        requirement = requirement.split(" --", 1)[0].strip()
    stop = len(requirement)
    for i, char in enumerate(requirement):
        if char in ("=", "<", ">", "~", "!", ";", "[", "@", " "):
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


class PythonDiff(BaseDiff):
    """Python AST-grep structural diff."""

    pass


class PythonAdapter(LanguageAdapter):
    """Python language adapter with multi-directory monorepo and AST-grep support."""

    @property
    def ecosystem(self) -> str:
        return "pypi"

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        # 1. Discover all pyproject.toml files across the entire repo
        pyproject_paths = find_manifest_files(repo_path, ["pyproject.toml"], METADATA.exclude_dirs)

        # 2. Discover all requirements files across the entire repo
        req_paths = find_manifest_files(
            repo_path,
            [
                "requirements.txt",
                "requirements-dev.txt",
                "requirements-test.txt",
                "requirements_dev.txt",
                "dev-requirements.txt",
            ],
            METADATA.exclude_dirs,
        )

        # 3. Discover setup.py / setup.cfg
        setup_paths = find_manifest_files(repo_path, ["setup.py", "setup.cfg"], METADATA.exclude_dirs)

        requirements: list[str] = []

        # Parse pyproject.toml
        for pyproject_path in pyproject_paths:
            try:
                with pyproject_path.open("rb") as fh:
                    data = tomllib.load(fh)
            except Exception:
                continue

            # Standard PEP 621 [project.dependencies]
            project = data.get("project", {})
            requirements.extend(project.get("dependencies", []))
            for group_reqs in project.get("optional-dependencies", {}).values():
                requirements.extend(group_reqs)

            # PEP 735 [dependency-groups]
            for group_reqs in data.get("dependency-groups", {}).values():
                if isinstance(group_reqs, list):
                    for item in group_reqs:
                        if isinstance(item, str):
                            requirements.append(item)

            # Poetry [tool.poetry.dependencies]
            poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
            for name in poetry_deps:
                if name.lower() != "python":
                    requirements.append(name)

        # Parse requirements*.txt
        for req_path in req_paths:
            try:
                raw_bytes = req_path.read_bytes()
                if b"\x00" in raw_bytes:
                    text = raw_bytes.decode("utf-16", errors="ignore")
                else:
                    text = raw_bytes.decode("utf-8", errors="ignore")
            except OSError:
                continue

            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                line = line.split("#", 1)[0].strip()
                if " --" in line:
                    line = line.split(" --", 1)[0].strip()
                parts = [p.strip() for p in line.split() if p.strip()]
                if len(parts) > 1 and not any(op in line for op in ("==", ">=", "<=", "~=", "!=")):
                    requirements.extend(parts)
                else:
                    requirements.append(line)

        # Parse setup.py / setup.cfg
        for setup_path in setup_paths:
            try:
                content = setup_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if setup_path.name == "setup.py":
                for match in _SETUP_REQUIRES_RE.finditer(content):
                    for item in match.group(1).split(","):
                        item = item.strip().strip("'\"")
                        if item:
                            requirements.append(item)
            elif setup_path.name == "setup.cfg":
                for match in _SETUP_CFG_REQ_RE.finditer(content):
                    for line in match.group(1).splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            requirements.append(line)

        if not requirements:
            return []

        names = {_requirement_name(r) for r in requirements}
        return [PythonDependency(name=n, version="*") for n in sorted(names) if n]

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        from resync.adapters.python.resolver import resolve_dependencies

        return PythonResolvedLockfile(dependencies=resolve_dependencies(dependencies, target_profile))

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        from resync.adapters.python.extract_api_diff import extract

        return extract(package, version_old, version_new, from_version=version_old, to_version=version_new)

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        """Generates a structural patch diff for record on file_path without modifying the file on disk."""
        return execute_structural_patch(file_path, record, language="python", diff_factory=PythonDiff)

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        return []


ADAPTER_CLASS = PythonAdapter
