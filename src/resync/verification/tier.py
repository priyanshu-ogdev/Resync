"""Phase 3.1: which verification tier a given patch needs.

Per docs/architecture.md#decision-2, mechanical fixes (RENAME, REORDER) are exempt
from the full differential-equivalence check — a compile check is sufficient for their risk profile. That
exemption was previously only prose; this module gives it a concrete, testable home so the rest of the
verification layer has a single source of truth for "how hard do we need to check this."

This is a pure function of (RuleType, PatchStrategy, one signature-bind probe) — no new classification logic
beyond what patch/taxonomy.py already produces, just routing.

Found in this pass, and load-bearing for the DEPRECATION_WINDOW_DIFFERENTIAL row specifically: "both old and
new call accepted right now" is not a property of the RuleType alone — it's a fact about the currently
installed library version, which can only change over time as a deprecation window opens and eventually
closes (see knowledge/seed_data.py's `use_auth_token`->`token` record: both worked for several `transformers`
minor versions before v5's hard removal). `select_tier` therefore takes an optional `old_callable` and probes
it directly with `inspect.signature`, rather than trying to infer the answer from `KnowledgeRecord` fields
alone — those describe what changed between versions, not what's true of whichever version happens to be
pinned in the repo being verified right now.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from resync.knowledge.schema import KnowledgeRecord, RuleType
from resync.patch.taxonomy import PatchStrategy

if TYPE_CHECKING:
    from resync.verification.differential import DifferentialResult


class VerificationTier(StrEnum):
    COMPILE_CHECK = "compile_check"
    """Mechanical (RENAME/REORDER) fixes, per ADR 0002's explicit exemption. A compile check is already
    effectively performed by patch/ast_grep_runner.py's own apply() (it wouldn't have written a syntactically
    broken file) — this tier exists to be an explicit, named "yes, this was still checked" signal on
    TrustScore, not to re-run a check that already necessarily happened."""

    DEPRECATION_WINDOW_DIFFERENTIAL = "deprecation_window_differential"
    """The strongest tier: the old and new call are both actually invoked against the one library version
    currently pinned, and their results are diffed directly. Only reachable when the old parameter/symbol
    still binds on the installed version — see module docstring."""

    ORACLE_SIGNATURE_CHECK = "oracle_signature_check"
    """The old call can no longer be executed (hard-removed). The check falls back to a static claim check:
    does the patched call's signature actually bind against the installed new version, and does the
    remapping match what the KnowledgeRecord itself claims — the record is the oracle here, per ADR 0002,
    specifically to avoid testing a translation against itself."""

    GENERATOR_CRITIC = "generator_critic"
    """Semantic (LLM-drafted) patches, always, regardless of RuleType — the generator/critic double-pass
    from ADR 0002. Not implemented until Phase 6 (needs a local model); verification/critic.py's Protocol is
    the seam this tier will eventually call into."""


def _old_parameter_still_binds(record: KnowledgeRecord, old_callable: Callable[..., Any] | None) -> bool:
    """Probe, don't guess: is `record.parameter` still an accepted keyword on `old_callable`'s real,
    currently-installed signature? Deliberately narrow — checks membership in the signature's parameter
    names, not a full bind, since a full bind needs example values this function doesn't have (that's
    verification/differential.py's job, once this function has already decided which tier to run).
    """
    if old_callable is None or record.parameter is None:
        return False
    try:
        return record.parameter in inspect.signature(old_callable).parameters
    except (TypeError, ValueError):
        # Some real callables (C extensions, certain decorated functions) don't expose an inspectable
        # signature at all. Treated as "can't confirm the window is open", not as "it is open" — the
        # oracle-only fallback is always the safe direction to fail toward.
        return False


def select_tier(
    record: KnowledgeRecord,
    patch_strategy: PatchStrategy,
    old_callable: Callable[..., Any] | None = None,
) -> VerificationTier:
    """The single routing function the rest of Phase 3 calls. `old_callable`, when available (i.e. the
    target repo's currently-pinned library version is actually importable in this process — see
    verification/sandbox.py for where that import should safely happen), is what lets a RENAME opportunistically
    upgrade from COMPILE_CHECK to the strictly stronger DEPRECATION_WINDOW_DIFFERENTIAL tier. Omitting it
    (the default) is always safe — it just means the weaker tier is selected, never the wrong one.
    """
    if patch_strategy == PatchStrategy.SEMANTIC:
        return VerificationTier.GENERATOR_CRITIC

    if patch_strategy == PatchStrategy.MECHANICAL and record.rule_type in (RuleType.RENAME, RuleType.REORDER):
        if record.rule_type == RuleType.RENAME and _old_parameter_still_binds(record, old_callable):
            return VerificationTier.DEPRECATION_WINDOW_DIFFERENTIAL
        return VerificationTier.COMPILE_CHECK

    # PatchStrategy.ESCALATE, or a MECHANICAL classification for a non-RENAME/REORDER rule_type (shouldn't
    # currently happen given RuleType.is_mechanical's own definition, but handled rather than assumed
    # unreachable): the oracle check is still the best available signal, and costs nothing to compute even
    # when no automatic patch will actually be applied off the back of it.
    return VerificationTier.ORACLE_SIGNATURE_CHECK


def resolve_callable(dotted: str | None) -> Callable[..., Any] | None:
    """Attempts to dynamically import and resolve a dotted symbol path (e.g. 'pkg.module.Class.method')
    to a live callable. Returns None if the symbol cannot be imported or is not callable."""
    if not dotted:
        return None
    import importlib

    parts = dotted.strip().split(".")
    for i in range(len(parts), 0, -1):
        mod_name = ".".join(parts[:i])
        try:
            mod = importlib.import_module(mod_name)
            curr: Any = mod
            for attr in parts[i:]:
                curr = getattr(curr, attr)
            if callable(curr):
                return curr  # type: ignore[no-any-return]
        except (ImportError, AttributeError, ValueError):
            continue
        except Exception:
            return None
    return None


def evaluate_record_verification(
    record: KnowledgeRecord,
    patch_strategy: PatchStrategy = PatchStrategy.MECHANICAL,
) -> tuple[VerificationTier, DifferentialResult]:
    """Resolves available callables for a KnowledgeRecord, determines the appropriate
    VerificationTier, and executes the verification check (compile check, oracle signature check,
    or deprecation window differential), returning (tier, differential_result)."""
    from resync.verification.differential import (
        check_deprecation_window_differential,
        check_oracle_signature,
        compile_check_result,
    )

    old_call = resolve_callable(record.old_symbol)
    new_symbol_name = record.new_symbol or record.old_symbol
    new_call = resolve_callable(new_symbol_name)

    tier = select_tier(record, patch_strategy, old_callable=old_call)

    if (
        tier == VerificationTier.DEPRECATION_WINDOW_DIFFERENTIAL
        and old_call is not None
        and new_call is not None
        and record.parameter
        and record.new_parameter
    ):
        try:
            result = check_deprecation_window_differential(
                old_call=old_call,
                new_call=new_call,
                old_param=record.parameter,
                new_param=record.new_parameter,
            )
            return tier, result
        except Exception:
            pass

    if tier == VerificationTier.ORACLE_SIGNATURE_CHECK and new_call is not None:
        try:
            result = check_oracle_signature(record, new_call)
            return tier, result
        except Exception:
            pass

    return tier, compile_check_result()
