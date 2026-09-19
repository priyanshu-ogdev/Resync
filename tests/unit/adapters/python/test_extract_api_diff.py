"""Unit tests for knowledge/extract_api_diff.py's correlation and reorder-detection heuristics.

Deliberately griffe-free: `_correlate_removed_parameter`, `_correlate_removed_object`, and `_detect_reorder`
are pure functions over plain name lists, tested here without importing `griffe` at all — griffe is not
installed in every dev/CI environment by default (it lives behind the `server` extra), and these heuristics'
correctness has nothing to do with griffe's own runtime behavior. `extract()` itself, which does call
griffe, is covered separately in tests/integration/test_extract_api_diff.py, which skips (not fakes) when
griffe isn't importable.
"""

from __future__ import annotations

from resync.adapters.python.extract_api_diff import (
    _best_name_match,
    _correlate_removed_object,
    _correlate_removed_parameter,
    _detect_reorder,
)


def test_correlate_removed_parameter_finds_a_close_rename() -> None:
    """The canonical, easy case: a removed parameter with a clearly similar newly-added replacement."""
    correlation = _correlate_removed_parameter(
        "per_gpu_train_batch_size",
        old_param_names=["per_gpu_train_batch_size", "learning_rate"],
        new_param_names=["per_device_train_batch_size", "learning_rate"],
    )
    assert correlation is not None
    assert correlation.new_name == "per_device_train_batch_size"
    assert 0.0 < correlation.confidence <= 1.0


def test_correlate_removed_parameter_ignores_preexisting_unrelated_params() -> None:
    """A parameter that was already present in the old signature is never a valid 'replacement' for a
    removed one, no matter how similar its name is — it was already there, so it can't be what the removed
    parameter became."""
    correlation = _correlate_removed_parameter(
        "no_cuda",
        old_param_names=["no_cuda", "use_cpu_cache"],  # use_cpu_cache pre-existed, not a real replacement
        new_param_names=["use_cpu_cache"],  # nothing new was actually added
    )
    assert correlation is None


def test_correlate_removed_parameter_returns_none_for_unrelated_names() -> None:
    """A genuinely unrelated rename (no shared spelling at all) is a known, honest limitation of
    name-similarity correlation — see extract_api_diff.py's module docstring. It must fall through to
    None (-> REMOVED_NO_REPLACEMENT at the caller), not force a low-confidence wrong guess."""
    correlation = _correlate_removed_parameter(
        "old_totally_unrelated_name",
        old_param_names=["old_totally_unrelated_name"],
        new_param_names=["xyz"],
    )
    assert correlation is None


def test_correlate_removed_object_same_shape_as_parameter_correlation() -> None:
    correlation = _correlate_removed_object(
        "AutoModelForVision2Seq",
        old_sibling_names=["AutoModelForVision2Seq", "AutoModelForCausalLM"],
        new_sibling_names=["AutoModelForImageTextToText", "AutoModelForCausalLM"],
    )
    assert correlation is not None
    assert correlation.new_name == "AutoModelForImageTextToText"


def test_correlate_removed_object_no_replacement_when_only_dissimilar_candidates_exist() -> None:
    """Mirrors the real AutoModelWithLMHead case from the manually-curated seed set: multiple newly-added
    siblings exist, but none is a confident 1:1 match, so this must return None rather than pick the least
    bad option — that's exactly the REMOVED_NO_REPLACEMENT case."""
    correlation = _correlate_removed_object(
        "AutoModelWithLMHead",
        old_sibling_names=["AutoModelWithLMHead"],
        new_sibling_names=["AutoModelForCausalLM", "AutoModelForMaskedLM", "AutoModelForSeq2SeqLM"],
    )
    assert correlation is None


def test_best_name_match_picks_the_highest_scoring_candidate() -> None:
    correlation = _best_name_match("use_auth_token", ["token", "use_auth", "something_else"])
    assert correlation is not None
    assert correlation.new_name == "use_auth"  # closer string match than the eventual real-world "token"


def test_best_name_match_returns_none_for_empty_candidates() -> None:
    assert _best_name_match("anything", []) is None


def test_detect_reorder_finds_a_pure_positional_swap() -> None:
    result = _detect_reorder(["host", "port", "timeout"], ["port", "host", "timeout"])
    assert result is not None
    old_order, new_order = result
    assert old_order == ["host", "port", "timeout"]
    assert new_order == ["port", "host", "timeout"]


def test_detect_reorder_returns_none_when_unchanged() -> None:
    assert _detect_reorder(["a", "b"], ["a", "b"]) is None


def test_detect_reorder_returns_none_when_parameter_set_differs() -> None:
    """A reorder plus an addition/removal is not a pure REORDER — deliberately ambiguous, and deliberately
    left for a human/SEMANTIC path rather than guessed at, per the function's own docstring."""
    assert _detect_reorder(["a", "b"], ["b", "a", "c"]) is None
