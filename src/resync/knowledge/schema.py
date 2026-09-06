"""The knowledge-record schema.

Per docs/architecture.md#knowledge-layer and the Vul-RAG template it follows (docs/research-foundations.md#3),
Resync never embeds raw prose chunks as its unit of retrieval. Every fact the system acts on is normalized
into a KnowledgeRecord first.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class RuleType(StrEnum):
    """The signature-change taxonomy from docs/architecture.md.

    This is the single most load-bearing classification in the system: it determines whether a change can be
    applied mechanically (ast-grep, no model call) or requires the semantic path (local LLM draft +
    differential-equivalence verification). See docs/adr/0003-deterministic-first-patching.md.
    """

    RENAME = "rename"
    REORDER = "reorder"
    SPLIT = "split"
    MERGE = "merge"
    RETURN_SHAPE_CHANGE = "return_shape_change"
    BEHAVIOR_CHANGE = "behavior_change"
    REMOVED_NO_REPLACEMENT = "removed_no_replacement"

    @property
    def is_mechanical(self) -> bool:
        """Whether this change type can be applied by ast-grep alone, with no LLM call.

        Everything else requires the differential/property-based equivalence check before it counts as
        verified — see docs/adr/0002-differential-equivalence-verification.md.
        """
        return self in (RuleType.RENAME, RuleType.REORDER)


class RecordSource(StrEnum):
    """Where a knowledge record's evidence came from — kept explicit so retrieval and trust scoring can
    weight sources differently rather than treating every record as equally authoritative."""

    COMPILER_WARNING = "compiler_warning"
    API_DIFF_TOOL = "api_diff_tool"
    CHANGELOG_EXTRACT = "changelog_extract"


class KnowledgeRecord(BaseModel):
    """A single, structured fact about how a package's public API changed between two versions.

    This is the unit Resync retrieves, not a raw text chunk. See docs/research-foundations.md#3 for why this
    schema exists instead of embedding changelog prose directly.
    """

    package: str
    ecosystem: Literal["pypi", "npm", "crates", "go", "maven"]
    old_symbol: str
    new_symbol: str | None = None  # None for RuleType.REMOVED_NO_REPLACEMENT
    from_version: str
    to_version: str
    rule_type: RuleType
    source: RecordSource
    confidence: float = Field(ge=0.0, le=1.0)
