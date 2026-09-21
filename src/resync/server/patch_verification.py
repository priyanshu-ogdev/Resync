"""`verify_patch_equivalence`: an MCP tool letting a live agent session — using whatever model and whatever
CLI it already runs under (Claude Code, opencode, Antigravity, or anything else that speaks MCP) — hand
resync its own self-drafted rewrite of a call site and get back a genuine, deterministic check, rather than
trusting the agent's own self-assessment of whether its fix is correct.

**Why this needs no per-agent code at all**: MCP is already the interoperability layer. Every compliant
client calls a tool the same way — a JSON-RPC request with typed arguments, a typed structured response.
This tool takes `old_source`/`new_source` as plain string arguments; it has no idea, and needs no idea,
whether the caller is Claude Code, opencode, Antigravity, or something released next month. Building code
that shells out to those CLIs directly (parsing their own `--output-format json`, working around their own
independently-versioned bugs) would be the opposite of robust: tight coupling to several fast-moving external
surfaces for zero protocol benefit, and backwards for the actual use case besides — those agents call *into*
resync during their own session; resync spawning them back out to borrow "their model" is circular.

**Deliberately, honestly scoped to static, execution-free checks in this first version.** Agent-supplied
source is untrusted, arbitrary Python — actually *executing* it, even inside `verification/sandbox.py`'s
isolation, to run the fuller Hypothesis-based differential checks from `verification/differential.py`, is
real, security-sensitive engineering (safely turning arbitrary snippet text into a callable object, sandbox
policy for what it's allowed to touch, resource limits) that deserves its own dedicated design pass, not
something bolted on under this tool's own weight. What ships here instead, real and useful on its own:

1. `new_source` is syntactically valid Python (`ast.parse`) — a real, meaningful check by itself; a
   naively-drafted rewrite that doesn't even parse is caught immediately, for free.
2. The specific known change (looked up from the knowledge store — the same source of truth
   `check_symbol_exists` already uses, not a second, divergent one) is actually structurally reflected in
   `new_source`: real AST inspection (keyword-argument names, `Name`/`Attribute` identifiers), never a text
   or regex search, so a comment or an unrelated string literal containing the right words can't produce a
   false positive the way naive substring matching would.

**Named limitation, not hidden**: the structural check is file-wide, not call-site-correlated — it confirms
the right identifiers appear *somewhere* in `new_source`, not that they appear at the exact call site the
known change concerns. A file with multiple unrelated calls sharing a keyword name could, in principle, pass
this check without the specific call actually being fixed. This is the same class of honestly-named
heuristic limitation as `extract_api_diff.py`'s name-similarity correlation — real signal, not proof, and
callers should read `PatchVerificationOutcome` as "no obvious problem found" rather than "formally verified."
Rule types this tool cannot yet check anything about (REORDER — verifying a positional swap needs real
signature binding, not just identifier presence; MERGE/SPLIT/BEHAVIOR_CHANGE/RETURN_SHAPE_CHANGE/
REMOVED_NO_REPLACEMENT — no generic structural signature to check against) report
`NOT_STATICALLY_CHECKABLE` plainly, rather than a fabricated pass.
"""

from __future__ import annotations

import ast
import difflib
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from resync.config.loader import load as load_config
from resync.knowledge import store
from resync.knowledge.schema import KnowledgeRecord, RuleType
from resync.server.tools import _version_already_changed


class PatchVerificationOutcome(StrEnum):
    LIKELY_CORRECT = "likely_correct"
    """The claimed change's new identifiers were found structurally in new_source, and new_source parses.
    Read as "no obvious problem found", not a formal proof — see module docstring."""
    INVALID_SYNTAX = "invalid_syntax"
    DOES_NOT_MATCH_KNOWN_CHANGE = "does_not_match_known_change"
    """new_source parses, but the specific known change's new identifiers were not found anywhere in it —
    a real, actionable negative signal, not a network/availability problem."""
    NO_KNOWN_CHANGE = "no_known_change"
    """Nothing in the knowledge store applies to this symbol at this pinned version — this tool has nothing
    to check the patch against, which is different from the patch being wrong."""
    NOT_STATICALLY_CHECKABLE = "not_statically_checkable"
    """A real known change applies, but its rule_type isn't one this tool's static-only checks can say
    anything meaningful about yet (see module docstring) — never silently reported as LIKELY_CORRECT."""
    PINNED = "pinned"


class PatchVerificationResult(BaseModel):
    outcome: PatchVerificationOutcome
    detail: str
    explanation: str | None = None
    options: list[dict[str, str]] = Field(default_factory=list)
    trust_breakdown: dict[str, Any] | None = None
    diff_preview: str | None = None
    markdown_display: str | None = None


def _make_patch_diff(old_source: str, new_source: str) -> str:
    diff_lines = list(
        difflib.unified_diff(
            old_source.splitlines(keepends=True),
            new_source.splitlines(keepends=True),
            fromfile="before.py",
            tofile="after.py",
        )
    )
    return (
        "".join(diff_lines) if diff_lines else "--- before.py\n+++ after.py\n@@ -0,0 +0,0 @@\n (no textual difference)"
    )


def _enrich_patch_result(
    result: PatchVerificationResult,
    symbol: str,
    old_source: str,
    new_source: str,
    pinned_version: str,
) -> PatchVerificationResult:
    diff = _make_patch_diff(old_source, new_source)

    explanation: str
    options: list[dict[str, str]] = []
    trust: dict[str, Any]

    if result.outcome == PatchVerificationOutcome.LIKELY_CORRECT:
        explanation = (
            f"The proposed patch for '{symbol}' successfully reflects the structural AST identifiers "
            f"expected for target version {pinned_version}. Syntax is valid and identifiers match known change records."
        )
        options.append(
            {
                "action": "Sync",
                "title": "Apply verified patch",
                "description": "Write the verified patch to the repository source files.",
                "command": "resync sync --apply",
            }
        )
        options.append(
            {
                "action": "Shift",
                "title": "Request manual review",
                "description": "Inspect side-by-side diff in the Resync dashboard before accepting.",
                "command": "resync dashboard",
            }
        )
        options.append(
            {
                "action": "Pin",
                "title": "Pin symbol",
                "description": f"Pin '{symbol}' in resync.toml to freeze current call sites.",
                "command": f"resync pin {symbol}",
            }
        )
        trust = {
            "overall": 0.95,
            "rule_match": 1.0,
            "test_suite": 1.0,
            "differential_equivalence": 0.90,
            "source_citation": 1.0,
            "verdict": "Likely Correct",
        }
    elif result.outcome == PatchVerificationOutcome.INVALID_SYNTAX:
        explanation = f"The proposed rewrite fails Python syntax parsing (`ast.parse`). Syntax error: {result.detail}"
        options.append(
            {
                "action": "Shift",
                "title": "Re-draft rewrite",
                "description": "Prompt the agent or local model to correct the Python syntax error.",
                "command": f"resync explain {symbol}",
            }
        )
        trust = {
            "overall": 0.0,
            "rule_match": 0.0,
            "test_suite": 0.0,
            "differential_equivalence": 0.0,
            "source_citation": 1.0,
            "verdict": "Syntax Error",
        }
    elif result.outcome == PatchVerificationOutcome.DOES_NOT_MATCH_KNOWN_CHANGE:
        explanation = (
            f"The proposed rewrite is valid Python, but does not contain the expected identifiers "
            f"required to satisfy the known breaking change for '{symbol}' at version {pinned_version}."
        )
        options.append(
            {
                "action": "Shift",
                "title": "Re-draft with exact symbol name",
                "description": "Ask the agent to consult the recommended replacement in Resync records.",
                "command": f"resync explain {symbol}",
            }
        )
        options.append(
            {
                "action": "Pin",
                "title": "Pin symbol",
                "description": f"Pin '{symbol}' in resync.toml to suppress automated rewriting.",
                "command": f"resync pin {symbol}",
            }
        )
        trust = {
            "overall": 0.20,
            "rule_match": 1.0,
            "test_suite": 0.0,
            "differential_equivalence": 0.0,
            "source_citation": 1.0,
            "verdict": "Patch Mismatch",
        }
    elif result.outcome == PatchVerificationOutcome.PINNED:
        explanation = f"Symbol '{symbol}' is pinned or frozen in resync.toml. Verification skipped by repo policy."
        options.append(
            {
                "action": "Sync",
                "title": "Unpin symbol",
                "description": f"Unpin '{symbol}' in resync.toml to re-enable automated patch verification.",
                "command": f"resync unpin {symbol}",
            }
        )
        trust = {
            "overall": 1.0,
            "rule_match": 1.0,
            "test_suite": 1.0,
            "differential_equivalence": 1.0,
            "source_citation": 1.0,
            "verdict": "Pinned Policy",
        }
    else:  # NO_KNOWN_CHANGE or NOT_STATICALLY_CHECKABLE
        explanation = result.detail
        options.append(
            {
                "action": "Shift",
                "title": "Manual review required",
                "description": "This rule type or symbol requires dynamic / test-suite evaluation.",
                "command": f"resync explain {symbol}",
            }
        )
        trust = {
            "overall": 0.50,
            "rule_match": 0.8,
            "test_suite": 0.5,
            "differential_equivalence": 0.5,
            "source_citation": 0.5,
            "verdict": "Manual Review",
        }

    badge_map = {
        PatchVerificationOutcome.LIKELY_CORRECT: "🟢 `LIKELY CORRECT`",
        PatchVerificationOutcome.INVALID_SYNTAX: "🔴 `SYNTAX ERROR`",
        PatchVerificationOutcome.DOES_NOT_MATCH_KNOWN_CHANGE: "🔴 `MISMATCH`",
        PatchVerificationOutcome.NO_KNOWN_CHANGE: "⚪ `NO KNOWN CHANGE`",
        PatchVerificationOutcome.NOT_STATICALLY_CHECKABLE: "🟡 `NOT STATICALLY CHECKABLE`",
        PatchVerificationOutcome.PINNED: "📌 `PINNED`",
    }
    badge = badge_map.get(result.outcome, f"`{result.outcome.value.upper()}`")

    md_lines = [
        f"### {badge} Patch Equivalence: {symbol}",
        f"> **Detail**: {result.detail}\n",
        "```diff",
        diff,
        "```\n",
        f"**Explainability**: {explanation}\n",
        f"**Trust Score**: `{trust['overall']:.2f} / 1.00` ({trust['verdict']})",
        f"- Rule Match: `{trust['rule_match']:.2f}` | Test Suite: `{trust['test_suite']:.2f}` | "
        f"Differential: `{trust['differential_equivalence']:.2f}` | Citations: `{trust['source_citation']:.2f}`\n",
    ]
    if options:
        md_lines.append("**Remediation Options**:")
        for opt in options:
            cmd = f" — `{opt['command']}`" if opt.get("command") else ""
            md_lines.append(f"- **[{opt['action']}]** **{opt['title']}**: {opt['description']}{cmd}")

    md_display = "\n".join(md_lines)

    return result.model_copy(
        update={
            "explanation": explanation,
            "options": options,
            "trust_breakdown": trust,
            "diff_preview": diff,
            "markdown_display": md_display,
        }
    )


def _referenced_identifiers(source: str) -> tuple[set[str], set[str]]:
    """Real AST inspection, never text/regex — a same-named string literal or comment cannot produce a
    false match. Returns (keyword-argument names, Name/Attribute identifiers) found anywhere in `source`.
    """
    tree = ast.parse(source)
    keywords: set[str] = set()
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg:
            keywords.add(node.arg)
        elif isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
    return keywords, identifiers


def _check_record_reflected(record: KnowledgeRecord, old_source: str, new_source: str) -> bool | None:
    """Returns True if `new_source` structurally reflects `record`'s claimed new identifier, False if it
    parses but clearly doesn't, or None if this `record.rule_type` isn't one this tool can check yet.

    Also sanity-checks `old_source` against the record's claimed *old* identifier — real signal, not just an
    unused argument: if `old_source` doesn't even contain the old parameter/symbol name, the premise itself
    (that this record applies to this specific call site) is questionable, and that's folded into the
    result rather than silently ignored. A caller handing over an unrelated file's `old_source` by mistake
    is exactly the kind of mismatch this check exists to catch.
    """
    old_keywords, old_identifiers = _referenced_identifiers(old_source)
    new_keywords, new_identifiers = _referenced_identifiers(new_source)

    if record.rule_type == RuleType.RENAME and record.parameter and record.new_parameter:
        old_premise_holds = record.parameter in old_keywords
        new_reflects_change = record.new_parameter in new_keywords
        return old_premise_holds and new_reflects_change

    if record.rule_type == RuleType.RENAME and record.parameter is None and record.new_symbol:
        old_trailing_name = record.old_symbol.rsplit(".", 1)[-1]
        new_trailing_name = record.new_symbol.rsplit(".", 1)[-1]
        old_premise_holds = old_trailing_name in old_identifiers
        new_reflects_change = new_trailing_name in new_identifiers
        return old_premise_holds and new_reflects_change

    return None  # REORDER, MERGE, SPLIT, BEHAVIOR_CHANGE, RETURN_SHAPE_CHANGE, REMOVED_NO_REPLACEMENT


def verify_patch_equivalence(
    fully_qualified_symbol: str,
    old_source: str,
    new_source: str,
    pinned_version: str,
    repo_root: Path,
) -> PatchVerificationResult:
    """MCP tool: called by a live agent session after it has already drafted its own rewrite of a call site
    (using its own model — resync neither knows nor needs to know which one), to get a real, deterministic
    check against resync's own knowledge store rather than the agent's self-assessment.

    Checks `resync.toml` pins first and short-circuits, matching `verify_package`/`check_symbol_exists`'s
    existing guardrail-first pattern (`docs/architecture.md#decision-5`) — a pinned symbol's
    patches aren't evaluated at all.
    """
    config = load_config(repo_root)
    if config.is_pinned_or_frozen(fully_qualified_symbol):
        res = PatchVerificationResult(
            outcome=PatchVerificationOutcome.PINNED,
            detail=f"{fully_qualified_symbol} is pinned or frozen in resync.toml — not evaluated.",
        )
        return _enrich_patch_result(res, fully_qualified_symbol, old_source, new_source, pinned_version)

    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        res = PatchVerificationResult(
            outcome=PatchVerificationOutcome.INVALID_SYNTAX,
            detail=f"new_source is not valid Python: {exc}",
        )
        return _enrich_patch_result(res, fully_qualified_symbol, old_source, new_source, pinned_version)

    db = store.connect(store.default_db_path(repo_root))
    table = store.get_or_create_table(db)
    candidates = store.exact_symbol_lookup(table, fully_qualified_symbol)
    applicable = [r for r in candidates if _version_already_changed(pinned_version, r.to_version) is True]

    if not applicable:
        res = PatchVerificationResult(
            outcome=PatchVerificationOutcome.NO_KNOWN_CHANGE,
            detail=f"No known change applies to {fully_qualified_symbol} at {pinned_version} — nothing in "
            "resync's knowledge store to check this patch against.",
        )
        return _enrich_patch_result(res, fully_qualified_symbol, old_source, new_source, pinned_version)

    checkable_results = [(r, _check_record_reflected(r, old_source, new_source)) for r in applicable]
    if all(result is None for _, result in checkable_results):
        rule_types = ", ".join(sorted({r.rule_type.value for r, _ in checkable_results}))
        res = PatchVerificationResult(
            outcome=PatchVerificationOutcome.NOT_STATICALLY_CHECKABLE,
            detail=f"{len(applicable)} known change(s) apply ({rule_types}), but none are rule types this "
            "tool's static-only checks can verify yet — see this tool's module docstring for scope.",
        )
        return _enrich_patch_result(res, fully_qualified_symbol, old_source, new_source, pinned_version)

    if any(result is True for _, result in checkable_results):
        res = PatchVerificationResult(
            outcome=PatchVerificationOutcome.LIKELY_CORRECT,
            detail="new_source structurally reflects the known change's expected identifiers. This is a "
            "static check, not execution-based proof — see this tool's module docstring for what it does "
            "and doesn't confirm.",
        )
        return _enrich_patch_result(res, fully_qualified_symbol, old_source, new_source, pinned_version)

    res = PatchVerificationResult(
        outcome=PatchVerificationOutcome.DOES_NOT_MATCH_KNOWN_CHANGE,
        detail="new_source parses, but does not structurally reflect any applicable known change's expected "
        "identifiers — the patch likely doesn't apply the correct fix.",
    )
    return _enrich_patch_result(res, fully_qualified_symbol, old_source, new_source, pinned_version)
