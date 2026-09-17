"""Repo-scanning helpers behind `resync check` and `resync sync`.

Two real, separate scans, matching server/tools.py's two MCP tools:

1. **Dependencies** — every package this repo actually declares (`pyproject.toml`'s `[project.dependencies]`
   and `[project.optional-dependencies]`), checked with `verify_package`.
2. **Symbols** — every fully-qualified `module.attr[.attr...]` expression actually used in the repo's Python
   source, resolved back to real import statements (not guessed from bare names), checked with
   `check_symbol_exists` against a real pinned version.

Both reuse `server/tools.py`'s functions directly rather than duplicating their pin/exception/store logic —
this module's job is purely "what should we ask", not "how do we answer".
"""

from __future__ import annotations

import ast
import importlib.metadata
import tomllib
from dataclasses import dataclass
from pathlib import Path

from resync.server.tools import VerificationOutcome, VerificationResult, check_symbol_exists, verify_package

_EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".resync",
    "build",
    "dist",
}

# PEP 508 requirement strings look like "name[extra]>=1.0,<2" or "name @ url" — only the bare distribution
# name is needed here (verify_package checks existence/advisories for the package itself, not a version
# range), so this deliberately stops at the first character that isn't part of a valid distribution name
# rather than writing a full PEP 508 parser for a CLI scan.
_NAME_STOP_CHARS = set("[]<>=!~; @")


def _requirement_name(requirement: str) -> str:
    stop = len(requirement)
    for ch in _NAME_STOP_CHARS:
        idx = requirement.find(ch)
        if idx != -1:
            stop = min(stop, idx)
    return requirement[:stop].strip()


def discover_python_files(repo_root: Path) -> list[Path]:
    """Every `.py` file under `repo_root`, skipping directories no scan should ever touch (VCS metadata,
    virtualenvs, caches, Resync's own `.resync/` state directory)."""
    files: list[Path] = []
    for path in repo_root.rglob("*.py"):
        if any(part in _EXCLUDED_DIR_NAMES for part in path.relative_to(repo_root).parts):
            continue
        files.append(path)
    return files


def discover_dependencies(repo_root: Path) -> list[str]:
    """Package names from `pyproject.toml`'s `[project.dependencies]` and every group under
    `[project.optional-dependencies]`. Returns `[]`, not an error, when there's no `pyproject.toml` — a
    project that doesn't declare dependencies this way (e.g. a bare `requirements.txt` project) isn't a scan
    failure, just nothing for this particular check to find."""
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        return []
    with pyproject_path.open("rb") as fh:
        data = tomllib.load(fh)

    project = data.get("project", {})
    requirements: list[str] = list(project.get("dependencies", []))
    for group_reqs in project.get("optional-dependencies", {}).values():
        requirements.extend(group_reqs)

    names = {_requirement_name(r) for r in requirements}
    return sorted(n for n in names if n)


def resolve_pinned_version(package: str, repo_root: Path) -> str | None:
    """The version of `package` this repo is actually pinned to, in priority order:

    1. `uv.lock`'s `[[package]]` table — the exact resolved version a real `uv sync` in this repo would
       install, which is the most trustworthy source when present.
    2. The version actually installed in the running Python environment (`importlib.metadata.version`) —
       meaningful when this scan itself is running inside the repo's own venv (e.g. as a pre-commit hook).

    Returns `None`, not a guess, when neither source has an answer — `check_symbol_exists` and this module's
    callers must treat that as "can't check this one", never as "assume some version".
    """
    uv_lock_path = repo_root / "uv.lock"
    if uv_lock_path.exists():
        with uv_lock_path.open("rb") as fh:
            lock_data = tomllib.load(fh)
        for entry in lock_data.get("package", []):
            if entry.get("name", "").lower() == package.lower():
                version = entry.get("version")
                if version:
                    return str(version)

    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


class _ImportedSymbolCollector(ast.NodeVisitor):
    """Resolves `module.attr[.attr...]` usages back to real import statements in the same file — never
    guesses a fully-qualified path from a bare name that could just as easily be a local variable. Only
    `import x[.y]`/`import x[.y] as z` and `from x[.y] import name[ as alias]` create an entry; anything not
    traceable to one of those is skipped rather than assumed."""

    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}  # local name -> fully-qualified base path
        self.symbols: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".")[0]
            self.aliases[local_name] = alias.name if alias.asname else alias.name.split(".")[0]

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None or node.level != 0:  # skip relative imports — no fully-qualified base exists
            return
        for alias in node.names:
            local_name = alias.asname or alias.name
            self.aliases[local_name] = f"{node.module}.{alias.name}"

    def visit_Attribute(self, node: ast.Attribute) -> None:
        chain = self._resolve_chain(node)
        if chain is not None:
            self.symbols.add(chain)
        self.generic_visit(node)

    def _resolve_chain(self, node: ast.Attribute) -> str | None:
        parts: list[str] = [node.attr]
        cursor: ast.expr = node.value
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if not isinstance(cursor, ast.Name):
            return None
        base = self.aliases.get(cursor.id)
        if base is None:
            return None
        return ".".join([base, *reversed(parts)])


def extract_fully_qualified_symbols(py_file: Path) -> set[str]:
    """Every `module.attr[.attr...]` symbol reference in `py_file` that traces back to a real `import`
    statement in that same file. Returns an empty set, without raising, for a file that doesn't parse (a
    scan over a whole repo shouldn't crash on one syntactically invalid or non-UTF-8 file)."""
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()
    collector = _ImportedSymbolCollector()
    collector.visit(tree)
    return collector.symbols


@dataclass
class DependencyFinding:
    package: str
    result: VerificationResult


@dataclass
class SymbolFinding:
    symbol: str
    files: list[Path]
    pinned_version: str | None
    result: VerificationResult | None  # None when pinned_version couldn't be resolved — not checked, not OK


def run_dependency_checks(repo_root: Path) -> list[DependencyFinding]:
    """Runs `verify_package` for every dependency `discover_dependencies` finds. One `httpx.Client` is
    shared across all calls (see `verify_package`'s own `client` parameter) so a repo with many dependencies
    doesn't open a new connection per package."""
    import httpx

    packages = discover_dependencies(repo_root)
    findings: list[DependencyFinding] = []
    with httpx.Client(timeout=10.0) as client:
        for package in packages:
            result = verify_package(package, "pypi", repo_root, client=client)
            findings.append(DependencyFinding(package=package, result=result))
    return findings


def run_symbol_checks(repo_root: Path) -> list[SymbolFinding]:
    """Runs `check_symbol_exists` for every fully-qualified symbol found across the repo's `.py` files,
    resolving each symbol's pinned version from its top-level package. A symbol used in more than one file
    is checked once and reported with every file it appears in, not once per occurrence."""
    symbol_to_files: dict[str, list[Path]] = {}
    for py_file in discover_python_files(repo_root):
        for symbol in extract_fully_qualified_symbols(py_file):
            symbol_to_files.setdefault(symbol, []).append(py_file)

    findings: list[SymbolFinding] = []
    version_cache: dict[str, str | None] = {}
    for symbol, files in sorted(symbol_to_files.items()):
        top_level_package = symbol.split(".")[0]
        if top_level_package not in version_cache:
            version_cache[top_level_package] = resolve_pinned_version(top_level_package, repo_root)
        pinned_version = version_cache[top_level_package]

        result = check_symbol_exists(symbol, pinned_version, repo_root) if pinned_version else None
        findings.append(SymbolFinding(symbol=symbol, files=files, pinned_version=pinned_version, result=result))
    return findings


def is_actionable(outcome: VerificationOutcome) -> bool:
    """True for outcomes a human should actually look at — excludes OK and PINNED, which are the two
    "nothing to do here" states. `CHECK_UNAVAILABLE` counts as actionable too: it's not a real finding, but
    silently dropping it would look identical to a clean OK, which is exactly the false reassurance this
    project's whole design exists to avoid — see server/tools.py's verify_package docstring."""
    return outcome not in (VerificationOutcome.OK, VerificationOutcome.PINNED)
