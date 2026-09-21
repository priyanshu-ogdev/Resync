"""The knowledge-record schema.

Per docs/architecture.md#knowledge-layer and the Vul-RAG template it follows
(docs/architecture.md#5-research-foundations--citations), Resync never embeds raw prose chunks as its unit
of retrieval. Every fact the system acts on is normalized into a KnowledgeRecord first.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RuleType(StrEnum):
    """The signature-change taxonomy from docs/architecture.md.

    This is the single most load-bearing classification in the system: it determines whether a change can be
    applied mechanically (ast-grep, no model call) or requires the semantic path (local LLM draft +
    differential-equivalence verification). See docs/architecture.md#decision-3-deterministic-first-patching.
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
        verified — see docs/architecture.md#decision-2-differential-equivalence-over-test-passes.
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

    This is the unit Resync retrieves, not a raw text chunk. See docs/architecture.md#5-research-foundations--citations
    for why this schema exists instead of embedding changelog prose directly.

    `old_symbol`/`new_symbol` are always the clean, fully-qualified symbol path (e.g.
    `transformers.PreTrainedModel.from_pretrained`) — never a call signature with placeholder arguments.
    When the change is to one keyword argument rather than the whole symbol (the common case — see the seed
    data's use_auth_token -> token example), `parameter`/`new_parameter` carry that detail instead.
    Conflating the two in a single free-text field was a real bug caught in review: it broke exact-symbol
    lookup, since nothing would ever query with a literal "symbol(arg=...)" string, and it didn't match
    router.py's own fully-qualified-symbol regex.

    `old_param_order`/`new_param_order` are used only for RuleType.REORDER — parallel lists of position
    labels (not the argument values themselves) showing how positional arguments were reordered, e.g.
    `old_param_order=["host", "port"]`, `new_param_order=["port", "host"]`. Both must be set, equal length,
    and a permutation of each other — enforced below, not left as an assumption for ast_grep_runner.py to
    discover the hard way.

    Review note: this model was originally unvalidated beyond field types, which let a RENAME record with no
    actual target (no changed new_symbol, no parameter/new_parameter pair) be constructed silently — the
    breakage only surfaced several layers downstream, inside ast_grep_runner.py, on whichever record happened
    to hit that path first. The validator below catches this at construction time instead, which is the
    correct place for it: a knowledge base that can represent nonsensical "changes" is a bug in the schema,
    not just in whatever code eventually tries to act on one.
    """

    package: str
    ecosystem: Literal["pypi", "npm", "crates", "go", "maven", "conan"]
    old_symbol: str
    new_symbol: str | None = None  # None only for RuleType.REMOVED_NO_REPLACEMENT
    parameter: str | None = None  # set when the change is to one keyword argument, not the whole symbol
    new_parameter: str | None = None  # the parameter's replacement, if `parameter` is set
    old_param_order: list[str] | None = None  # REORDER only — see class docstring
    new_param_order: list[str] | None = None  # REORDER only — see class docstring
    from_version: str
    to_version: str
    rule_type: RuleType
    source: RecordSource
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_mechanical_fields(self) -> KnowledgeRecord:
        if self.rule_type == RuleType.REMOVED_NO_REPLACEMENT and self.new_symbol is not None:
            raise ValueError("REMOVED_NO_REPLACEMENT records must have new_symbol=None")

        if self.rule_type == RuleType.RENAME:
            whole_symbol_renamed = self.new_symbol is not None and self.new_symbol != self.old_symbol
            parameter_renamed = self.parameter is not None and self.new_parameter is not None
            if not (whole_symbol_renamed or parameter_renamed):
                raise ValueError(
                    "RENAME records need either a changed new_symbol or a parameter/new_parameter pair — "
                    "a rename with no actual target is not a valid record"
                )

        if self.rule_type == RuleType.REORDER:
            if not self.old_param_order or not self.new_param_order:
                raise ValueError("REORDER records require both old_param_order and new_param_order")
            if len(self.old_param_order) != len(self.new_param_order):
                raise ValueError("REORDER's old_param_order and new_param_order must be the same length")
            if set(self.old_param_order) != set(self.new_param_order):
                raise ValueError("REORDER's new_param_order must be a permutation of old_param_order")

        return self
