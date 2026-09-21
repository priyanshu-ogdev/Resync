"""The five-function adapter interface every language plugs in through.

See docs/multi-language-adapters.md for the concrete tool each language's adapter wraps. The core
(retrieval, sandboxing, trust scoring, PR generation, resync.toml handling) is written once against this
interface and never branches on language name directly — a new language is a new implementation of this
Protocol, not a new code path in the core.

## Adding a new language

1. Create ``src/resync/adapters/<lang>/adapter.py`` with a class implementing ``LanguageAdapter``.
2. Expose ``METADATA: AdapterMetadata`` and ``ADAPTER_CLASS = YourAdapter`` at module level.
3. The registry auto-discovers it via directory scan and pip entry-points automatically.
   No changes to ``registry.py`` or any other core file are required.

Alternatively, publish a ``resync-adapter-<lang>`` pip package that registers itself under the
``resync.adapters`` entry-points group — the registry discovers it at runtime without any Resync
source changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from resync.knowledge.schema import KnowledgeRecord

# ---------------------------------------------------------------------------
# Shared data-transfer types
# ---------------------------------------------------------------------------


class Dependency(Protocol):
    name: str
    version: str


class ResolvedLockfile(Protocol):
    dependencies: list[Dependency]


class Diff(Protocol):
    file_path: Path
    old_text: str
    new_text: str

    def __init__(self, file_path: Path, old_text: str, new_text: str) -> None: ...

    @property
    def has_changes(self) -> bool: ...

    def unified_diff(self, context_lines: int = 3) -> str: ...


@dataclass
class BaseDiff:
    """Standard, concrete Diff implementation with rich unified diff support."""

    file_path: Path
    old_text: str
    new_text: str

    @property
    def has_changes(self) -> bool:
        return self.old_text != self.new_text

    def unified_diff(self, context_lines: int = 3) -> str:
        if not self.has_changes:
            return ""
        import difflib

        path_str = self.file_path.as_posix()
        lines = difflib.unified_diff(
            self.old_text.splitlines(keepends=True),
            self.new_text.splitlines(keepends=True),
            fromfile=f"a/{path_str}",
            tofile=f"b/{path_str}",
            n=context_lines,
        )
        return "".join(lines)


class DeprecationWarning_(Protocol):
    symbol: str
    message: str
    file_path: Path
    line: int


# ---------------------------------------------------------------------------
# Universal multi-directory manifest discovery
# ---------------------------------------------------------------------------

DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".resync",
        "build",
        "dist",
        "target",
        ".gradle",
        ".idea",
        ".vscode",
        "cmake-build-debug",
        "cmake-build-release",
        "vendor",
    }
)


def find_manifest_files(
    repo_path: Path,
    file_names: list[str] | tuple[str, ...],
    exclude_dirs: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
) -> list[Path]:
    """Recursively discover manifest files matching `file_names` under `repo_path`.

    Root manifests appear first in the returned list, followed by recursively discovered
    manifests in submodules/packages. Directories matching `exclude_dirs` are pruned.
    """
    excludes = DEFAULT_EXCLUDE_DIRS if exclude_dirs is None else (DEFAULT_EXCLUDE_DIRS | set(exclude_dirs))
    manifests: list[Path] = []
    seen: set[Path] = set()

    # 1. Root-level checks (preserves exact root priority)
    for name in file_names:
        candidate = repo_path / name
        if candidate.is_file():
            manifests.append(candidate)
            seen.add(candidate.resolve())

    # 2. Recursive traversal
    try:
        for root_dir, dirs, files in os.walk(repo_path):
            # Prune excluded directories in-place so os.walk does not descend into them
            dirs[:] = [d for d in dirs if d not in excludes]
            current_path = Path(root_dir)
            try:
                rel = current_path.relative_to(repo_path)
            except ValueError:
                continue

            # Check if any parent component is excluded
            if any(part in excludes for part in rel.parts):
                continue

            for f in files:
                if f in file_names:
                    p = current_path / f
                    resolved = p.resolve()
                    if resolved not in seen and p.is_file():
                        manifests.append(p)
                        seen.add(resolved)
    except OSError:
        pass

    return manifests


def execute_structural_patch(
    file_path: Path,
    record: KnowledgeRecord,
    language: str,
    diff_factory: type[Diff] = BaseDiff,
) -> Diff:
    """Apply an ast-grep structural patch to a file without modifying it on disk.

    Returns a Diff object containing the original and modified contents.
    """
    if not file_path.exists():
        return diff_factory(file_path=file_path, old_text="", new_text="")

    try:
        old_text = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return diff_factory(file_path=file_path, old_text="", new_text="")

    from resync.patch import ast_grep_runner

    matches = ast_grep_runner.preview(record, file_path, language=language)
    if not matches:
        return diff_factory(file_path=file_path, old_text=old_text, new_text=old_text)

    import tempfile

    suffix = file_path.suffix or f".{language}"
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as tmp:
        tmp.write(old_text)
        temp_path = Path(tmp.name)

    try:
        ast_grep_runner.apply(record, temp_path, language=language)
        new_text = temp_path.read_text(encoding="utf-8", errors="ignore")
    finally:
        temp_path.unlink(missing_ok=True)

    return diff_factory(file_path=file_path, old_text=old_text, new_text=new_text)


# ---------------------------------------------------------------------------
# Declarative adapter metadata — the plugin contract
# ---------------------------------------------------------------------------


@dataclass
class AdapterMetadata:
    """Declarative description of a language adapter.

    Each adapter module exposes a module-level ``METADATA: AdapterMetadata`` constant and an
    ``ADAPTER_CLASS`` reference. The registry reads these to perform language detection and
    capability gating without instantiating the adapter class first.

    Detection logic
    ---------------
    An adapter is activated when **both** conditions are met:

    1. **Repo signal** — the repository contains at least one file matching ``manifest_files``
       (exact name at root or in immediate subdirs) or ``manifest_globs`` (recursive glob,
       respecting ``exclude_dirs``).

    2. **Capability gate** — all entries in ``required_tools`` resolve via ``shutil.which()``.
       If ``required_tools`` is empty the adapter always passes the gate. Missing entries in
       ``optional_tools`` are skipped gracefully.

    Priority
    --------
    When multiple adapters match the same repo (polyglot), all are returned by ``get_adapters()``.
    ``get_adapter()`` returns the highest-``priority`` one.

    Third-party adapters
    --------------------
    Any pip package may expose adapters by registering under the ``resync.adapters`` entry-points
    group::

        # In resync-adapter-ruby/pyproject.toml
        [project.entry-points."resync.adapters"]
        ruby = "resync_adapter_ruby:RubyAdapter"

    The module must expose ``METADATA`` and ``ADAPTER_CLASS`` at module level. The registry
    gives entry-point adapters priority over built-in ones with the same ``name``, allowing
    drop-in overrides.
    """

    # --- Identity ---
    name: str
    """Short identifier, e.g. ``"kotlin"``. Must be unique across all discovered adapters."""

    ecosystem: str
    """OSV/advisory ecosystem name: ``"pypi"``, ``"crates"``, ``"npm"``, ``"maven"``,
    ``"go"``, ``"conan"``, ``"rubygems"``, ``"nuget"``, …"""

    display_name: str
    """Human-readable name shown in ``resync info`` / ``resync doctor``."""

    # --- Repo-side detection signals (hints, not hard requirements) ---
    manifest_files: list[str] = field(default_factory=list)
    """Exact filenames to look for at the repo root or one level below.
    Example: ``["Cargo.toml", "Cargo.lock"]``."""

    manifest_globs: list[str] = field(default_factory=list)
    """Recursive glob patterns applied from the repo root.
    Example: ``["**/*.rs"]``. Only used when ``manifest_files`` produces no hit."""

    exclude_dirs: list[str] = field(default_factory=list)
    """Directory names to skip during manifest detection.
    Example: ``["target", ".git", "node_modules"]``."""

    # --- System-side capability requirements ---
    required_tools: list[str] = field(default_factory=list)
    """Binaries that **must** be on PATH for this adapter to function at all.
    The adapter is silently skipped if any are missing.
    Example: ``["go"]`` for the Go adapter."""

    optional_tools: list[str] = field(default_factory=list)
    """Binaries used when available, skipped gracefully when absent.
    Example: ``["gopls", "staticcheck"]`` for the Go adapter."""

    # --- Registry behaviour ---
    priority: int = 50
    """Determines ordering when multiple adapters match the same repo (polyglot repos).
    Higher = preferred as the primary adapter. Python=100, Rust=80, TS=75, Go=70, Kotlin=60."""

    allow_partial: bool = True
    """If ``True`` (default), activate even when ``optional_tools`` are absent.
    Only set ``False`` when the adapter cannot function without every declared tool."""


# ---------------------------------------------------------------------------
# The five-function adapter Protocol
# ---------------------------------------------------------------------------


class LanguageAdapter(Protocol):
    """Implement all five methods (plus ``ecosystem``) to add support for a new language.

    Every implementation should shell out to that ecosystem's native, purpose-built tool rather than
    reimplementing logic in Python — see docs/multi-language-adapters.md for why, and which tool each
    language uses.

    Module-level exports required by the registry (not part of the Protocol instance):

    .. code-block:: python

        METADATA: AdapterMetadata = AdapterMetadata(...)
        ADAPTER_CLASS = YourAdapterClass
    """

    @property
    def ecosystem(self) -> str:
        """The ecosystem name this adapter checks against, in the form used by this project's own
        KnowledgeRecord/OSV API calls: 'pypi', 'crates', 'npm', 'go', 'maven'. Each concrete adapter
        must implement this — the scan layer uses it to pass the right ecosystem to verify_package
        instead of hardcoding 'pypi' for every repo regardless of what language it actually uses.
        """
        ...

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        """Read the ecosystem's lockfile/manifest into a normalized dependency list."""
        ...

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        """Shell out to the ecosystem's native resolver against a chosen target profile.

        Never reimplement a dependency solver — see docs/architecture.md#target-stack-resolution.
        """
        ...

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        """Produce structured KnowledgeRecords for what changed between two versions of a package."""
        ...

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        """Apply a mechanical fix via ast-grep. Only called for record.rule_type.is_mechanical cases —
        semantic cases go through the local-model draft + differential-equivalence path instead."""
        ...

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        """Parse this ecosystem's own compiler/runtime warning format for live drift signals."""
        ...
