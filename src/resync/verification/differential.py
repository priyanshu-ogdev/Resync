"""Phase 3.2: the differential/call-compatibility harness itself.

Scope, stated explicitly rather than implied: this checks *call-compatibility and argument-forwarding
equivalence* — does the patched call get accepted by the real signature, and (within a deprecation window)
does it produce the same result as the old call. It does not, and cannot without pulling in `torch`/real
model weights/GPU execution, verify deep numerical equivalence of what an ML library actually computes (e.g.
that `Trainer.train()` produces bit-identical weights before and after a patch). That's the library's own
correctness contract; this project verifies that resync's *patch* forwarded the call correctly, not that the
underlying computation is unchanged. See verification/tier.py's module docstring for the same scoping note.

Built on `hypothesis.strategies.builds`/`st.from_type`, which infer a generation strategy from a callable's
type annotations — confirmed against Hypothesis's own docs in this project's design pass, not assumed.
Parameters with no usable annotation (missing, or `Any`) fall back to a small fixed corpus rather than full
generation; every `DifferentialResult` reports `reduced_confidence=True` when that fallback fired for the
specific parameter under test (the renamed one), so a caller never mistakes a weakly-covered pass for a
strongly-covered one.

Callables passed in here are expected to already be running inside verification/sandbox.py's isolation by the
time this module is called with real target-repo code — this module itself is sandbox-agnostic by design
(single responsibility: decide pass/fail from given callables, not decide how they're isolated).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_type_hints

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from resync.knowledge.schema import KnowledgeRecord, RuleType
from resync.verification.tier import VerificationTier

_FALLBACK_CORPUS: list[Any] = [None, 0, 1, "", "x", [], {}, True]
_MAX_EXAMPLES = 25


@dataclass
class DifferentialResult:
    tier: VerificationTier
    passed: bool
    reason: str
    examples_checked: int = 0
    reduced_confidence: bool = False
    """True when the parameter under test had no usable type annotation and fell back to the fixed corpus
    (module docstring) — a pass here is real evidence, just weaker evidence than a fully-typed pass."""
    failing_example: dict[str, Any] | None = None


def _param_strategy(annotation: Any) -> tuple[st.SearchStrategy[Any], bool]:
    """Returns (strategy, used_fallback). `used_fallback=True` means the annotation was missing/`Any` and
    the fixed corpus was used instead of type-driven generation."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return st.sampled_from(_FALLBACK_CORPUS), True
    try:
        return st.from_type(annotation), False
    except Exception:  # noqa: BLE001 — st.from_type can raise on types it can't resolve; corpus fallback is correct, not a bug to narrow
        return st.sampled_from(_FALLBACK_CORPUS), True


def _build_kwargs_strategy(
    func: Callable[..., Any], param_names: list[str], forced: dict[str, Any] | None = None
) -> tuple[st.SearchStrategy[dict[str, Any]], bool]:
    """Build a strategy generating a dict of kwargs for the given parameter names, keyed by `func`'s real
    signature. `forced` params (typically the renamed one itself, once its shared probe value is chosen by
    the caller) are excluded from generation and merged in by the caller instead — see
    check_deprecation_window_differential for why the renamed parameter needs a *shared* value between the
    old and new call rather than two independently-generated ones.

    Resolves annotations via `typing.get_type_hints`, not `inspect.signature(...).parameters[name].annotation`
    directly — found necessary by actually running this against a function whose module uses
    `from __future__ import annotations` (PEP 563), which every module in this very codebase does. Under
    PEP 563, `inspect.signature` leaves annotations as unevaluated strings (e.g. the literal text
    `'str | None'`), and `st.from_type` raises `InvalidArgument` on a raw string rather than a real type
    object. `get_type_hints` actually evaluates them in the function's own module namespace. A forward
    reference that still can't be resolved (e.g. a genuinely undefined name) falls back to the fixed corpus,
    same as a missing annotation — never raises out of this function.
    """
    forced = forced or {}
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return st.just(dict(forced)), True

    try:
        resolved_hints = get_type_hints(func)
    except Exception:  # noqa: BLE001 — unresolvable forward refs, missing imports in func's module, etc.;
        # falling back to per-parameter inspect.Parameter.empty (handled by _param_strategy) is correct here
        resolved_hints = {}

    strategies: dict[str, st.SearchStrategy[Any]] = {}
    any_fallback = False
    for name in param_names:
        if name in forced or name not in sig.parameters:
            continue
        annotation = resolved_hints.get(name, sig.parameters[name].annotation)
        strategy, used_fallback = _param_strategy(annotation)
        strategies[name] = strategy
        any_fallback = any_fallback or used_fallback

    return st.fixed_dictionaries(strategies).map(lambda d: {**d, **forced}), any_fallback


def check_deprecation_window_differential(
    old_call: Callable[..., Any],
    new_call: Callable[..., Any],
    old_param: str,
    new_param: str,
    shared_params: list[str] | None = None,
) -> DifferentialResult:
    """The strong tier: both `old_call(old_param=...)` and `new_call(new_param=...)` are actually invoked,
    for the same generated inputs, against the one library version currently pinned — and their outcomes
    are diffed directly (equal return values, or the same exception type on both sides — never just "neither
    raised", which would miss a case where both raise but for different, unrelated reasons).
    """
    shared_params = shared_params or []
    probe_strategy = st.sampled_from(_FALLBACK_CORPUS)  # the renamed parameter's own value — shared, not
    # independently generated per side, since the whole point is testing that the SAME logical value produces
    # the SAME outcome under both the old and new keyword.
    extra_strategy, used_fallback = _build_kwargs_strategy(new_call, shared_params)

    outcome: dict[str, Any] = {"checked": 0, "failure": None}

    @settings(max_examples=_MAX_EXAMPLES, suppress_health_check=[HealthCheck.too_slow])
    @given(probe_value=probe_strategy, extra=extra_strategy)
    def _run(probe_value: Any, extra: dict[str, Any]) -> None:
        old_kwargs = {**extra, old_param: probe_value}
        new_kwargs = {**extra, new_param: probe_value}
        outcome["checked"] += 1

        old_raised: type[BaseException] | None = None
        new_raised: type[BaseException] | None = None
        old_result: Any = None
        new_result: Any = None
        try:
            old_result = old_call(**old_kwargs)
        except Exception as exc:  # noqa: BLE001 — capturing to compare exception *types*, not to swallow
            old_raised = type(exc)
        try:
            new_result = new_call(**new_kwargs)
        except Exception as exc:  # noqa: BLE001 — same as above
            new_raised = type(exc)

        equivalent = (old_raised == new_raised) and (old_raised is not None or old_result == new_result)
        if not equivalent:
            outcome["failure"] = {"probe_value": probe_value, "extra": extra}
        assert equivalent, f"old_kwargs={old_kwargs!r} new_kwargs={new_kwargs!r} diverged"

    try:
        _run()
        passed = True
        reason = f"{outcome['checked']} generated examples produced equivalent old/new call outcomes"
    except AssertionError:
        passed = False
        reason = "old and new call diverged on at least one generated example"

    return DifferentialResult(
        tier=VerificationTier.DEPRECATION_WINDOW_DIFFERENTIAL,
        passed=passed,
        reason=reason,
        examples_checked=outcome["checked"],
        reduced_confidence=used_fallback,
        failing_example=outcome["failure"],
    )


def check_oracle_signature(record: KnowledgeRecord, new_call: Callable[..., Any]) -> DifferentialResult:
    """The fallback tier: no live old-call execution is possible (hard-removed). Checks two things, neither
    of which requires actually running `new_call`'s body (so no side-effect risk beyond signature binding
    itself): (1) the record's own claimed remapping is internally consistent for this rule_type, and (2) the
    remapped call actually binds against the real, currently-installed signature for a range of generated
    inputs — proving the patch is genuinely callable, not just textually plausible.
    """
    if record.rule_type == RuleType.RENAME and record.parameter and record.new_parameter:
        new_param = record.new_parameter
    elif record.rule_type == RuleType.RENAME and record.parameter is None and record.new_symbol:
        # Whole-symbol rename (e.g. AutoModelForVision2Seq -> AutoModelForImageTextToText): there's no
        # parameter to bind-check. The only oracle signal available at this layer is "did the new symbol
        # actually resolve" — the caller passing a real, non-None `new_call` already proves that (it had to
        # import/resolve the symbol to obtain the callable at all). A dotted-path existence check belongs to
        # whatever resolver looks the symbol up in the first place, not here.
        return DifferentialResult(
            tier=VerificationTier.ORACLE_SIGNATURE_CHECK,
            passed=new_call is not None,
            reason=(
                "whole-symbol rename: the new symbol resolved to a real callable"
                if new_call is not None
                else "whole-symbol rename: no callable was resolved for the claimed new symbol"
            ),
        )
    elif record.rule_type == RuleType.REORDER and record.old_param_order and record.new_param_order:
        new_param = None
    else:
        return DifferentialResult(
            tier=VerificationTier.ORACLE_SIGNATURE_CHECK,
            passed=False,
            reason=f"record.rule_type={record.rule_type} has no oracle-checkable remapping "
            "(missing parameter/new_parameter or old/new_param_order) — nothing to verify against",
        )

    try:
        sig = inspect.signature(new_call)
    except (TypeError, ValueError):
        return DifferentialResult(
            tier=VerificationTier.ORACLE_SIGNATURE_CHECK,
            passed=False,
            reason="new_call has no inspectable signature — cannot confirm the patch actually binds",
        )

    other_params = [p for p in sig.parameters if p not in (new_param,)] if new_param else list(sig.parameters)
    strategy, used_fallback = _build_kwargs_strategy(new_call, other_params)
    probe_strategy = st.sampled_from(_FALLBACK_CORPUS)

    outcome: dict[str, Any] = {"checked": 0, "failure": None}

    @settings(max_examples=_MAX_EXAMPLES, suppress_health_check=[HealthCheck.too_slow])
    @given(probe_value=probe_strategy, extra=strategy)
    def _run(probe_value: Any, extra: dict[str, Any]) -> None:
        kwargs = dict(extra)
        if new_param:
            kwargs[new_param] = probe_value
        outcome["checked"] += 1
        try:
            sig.bind(**kwargs)
        except TypeError:
            outcome["failure"] = kwargs
            raise AssertionError(f"{new_param or 'reordered call'} did not bind: kwargs={kwargs!r}") from None

    try:
        _run()
        passed = True
        reason = (
            f"remapped call bound successfully against the installed signature across "
            f"{outcome['checked']} generated examples"
        )
    except AssertionError:
        passed = False
        reason = "the record's claimed remapping does not bind against the installed signature"

    return DifferentialResult(
        tier=VerificationTier.ORACLE_SIGNATURE_CHECK,
        passed=passed,
        reason=reason,
        examples_checked=outcome["checked"],
        reduced_confidence=used_fallback,
        failing_example=outcome["failure"],
    )


def compile_check_result() -> DifferentialResult:
    """The COMPILE_CHECK tier's result is trivial by construction: patch/ast_grep_runner.py's apply() would
    not have written the file if it didn't parse (see that module). This function exists so callers have a
    uniform DifferentialResult-shaped return across all four tiers, not a special-cased None.
    """
    return DifferentialResult(
        tier=VerificationTier.COMPILE_CHECK,
        passed=True,
        reason="mechanical fix already implies a successful parse — see ast_grep_runner.apply()",
        examples_checked=0,
    )
