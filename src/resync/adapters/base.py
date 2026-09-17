"""The five-function adapter interface every language plugs in through.

See docs/multi-language-adapters.md for the concrete tool each language's adapter wraps. The core
(retrieval, sandboxing, trust scoring, PR generation, resync.toml handling) is written once against this
interface and never branches on language name directly — a new language is a new implementation of this
Protocol, not a new code path in the core.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from resync.knowledge.schema import KnowledgeRecord


class Dependency(Protocol):
    name: str
    version: str


class ResolvedLockfile(Protocol):
    dependencies: list[Dependency]


class Diff(Protocol):
    file_path: Path
    old_text: str
    new_text: str


class DeprecationWarning_(Protocol):
    symbol: str
    message: str
    file_path: Path
    line: int


class LanguageAdapter(Protocol):
    """Implement all five methods to add support for a new language.

    Every implementation should shell out to that ecosystem's native, purpose-built tool rather than
    reimplementing logic in Python — see docs/multi-language-adapters.md for why, and which tool each
    language uses.
    """

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
