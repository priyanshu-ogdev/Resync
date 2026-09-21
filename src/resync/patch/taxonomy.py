"""Given a KnowledgeRecord, decide how it should be fixed: mechanical, semantic, or escalate.

This is more than record.rule_type.is_mechanical alone (docs/architecture.md#decision-3-deterministic-first-patching):
resync.toml's confidence thresholds (config/schema.py's ConfidenceConfig) matter too — a RENAME with
suspiciously low confidence shouldn't skip verification just because rename-in-general is usually safe.

Caller contract worth stating explicitly, not just implying: PatchStrategy.MECHANICAL means "ast-grep can
express and correctly apply this fix in one shot" — it does not, by itself, guarantee safety on a repeating
unattended schedule. RENAME and REORDER differ here even though both are MECHANICAL on the first property:
RENAME is naturally idempotent (the old name stops existing once fixed), but REORDER is not (a positional
swap matches its own already-fixed output just as validly and swaps back) — see patch/ast_grep_runner.py's
module docstring, finding 7. That gap is now closed at the `apply()` layer: passing `repo_root` to
`ast_grep_runner.apply()` activates the `resync.toml`-persisted applied-already guard
(`config.schema.AppliedFix`), so a caller wiring this into the scheduled sweep
(docs/architecture.md#two-speeds) gets safe unattended REORDER application as long as it always passes
`repo_root`. Omitting `repo_root` (e.g. a one-off interactive fix) restores the original, ledger-free,
non-idempotent behavior — MECHANICAL alone still doesn't imply schedule-safety independent of how the
caller invokes `apply()`.
"""

from __future__ import annotations

from enum import StrEnum

from resync.knowledge.schema import KnowledgeRecord, RuleType


class PatchStrategy(StrEnum):
    MECHANICAL = "mechanical"  # ast-grep, no LLM call — see module docstring for the scheduling caveat
    SEMANTIC = "semantic"  # local LLM draft + differential-equivalence verification
    ESCALATE = "escalate"  # no safe automatic fix exists — needs a resync.toml decision


def classify(record: KnowledgeRecord, confidence_threshold: float = 0.95) -> PatchStrategy:
    """confidence_threshold should come from the project's resync.toml `[confidence] auto_apply_above`
    (config/schema.py's ConfidenceConfig) — passed explicitly rather than imported/loaded here, so this
    function stays pure and independently testable."""
    if record.rule_type == RuleType.REMOVED_NO_REPLACEMENT:
        return PatchStrategy.ESCALATE
    if record.rule_type.is_mechanical and record.confidence >= confidence_threshold:
        return PatchStrategy.MECHANICAL
    return PatchStrategy.SEMANTIC
