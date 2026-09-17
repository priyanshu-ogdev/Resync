"""Unit tests for verification/differential.py.

Includes the Phase 3.6 labeled-mutant pattern directly at the unit level: for every "correct" check, a
deliberately-broken mutant variant is also checked, asserting the harness rejects it. A false negative here
(a mutant that passes) is the exact failure mode this whole project exists to prevent — see
docs/implementation-plan.md's Phase 3 exit criteria.
"""

from __future__ import annotations

from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType
from resync.verification.differential import (
    check_deprecation_window_differential,
    check_oracle_signature,
    compile_check_result,
)
from resync.verification.tier import VerificationTier


def _use_auth_token_record() -> KnowledgeRecord:
    """Mirrors the real seed record and tests/fixtures/transformers-param-rename/ fixture."""
    return KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.PreTrainedModel.from_pretrained",
        new_symbol="transformers.PreTrainedModel.from_pretrained",
        parameter="use_auth_token",
        new_parameter="token",
        from_version="<4.32.0",
        to_version=">=4.32.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.98,
    )


# --- DEPRECATION_WINDOW_DIFFERENTIAL -----------------------------------------------------------------


def test_deprecation_window_differential_passes_on_a_genuinely_equivalent_pair() -> None:
    def old_from_pretrained(name: str, use_auth_token: str | None = None) -> tuple[str, str | None]:
        return (name, use_auth_token)

    def new_from_pretrained(name: str, token: str | None = None) -> tuple[str, str | None]:
        return (name, token)

    result = check_deprecation_window_differential(
        old_call=old_from_pretrained,
        new_call=new_from_pretrained,
        old_param="use_auth_token",
        new_param="token",
        shared_params=["name"],
    )
    assert result.passed is True
    assert result.tier == VerificationTier.DEPRECATION_WINDOW_DIFFERENTIAL
    assert result.examples_checked > 0


def test_deprecation_window_differential_catches_a_mutant_that_drops_the_value() -> None:
    """Mutant: the new call silently ignores the renamed parameter entirely — a real, plausible patch bug
    (e.g. the ast-grep rewrite renamed the keyword but the surrounding call site had a typo)."""

    def old_from_pretrained(name: str, use_auth_token: str | None = None) -> tuple[str, str | None]:
        return (name, use_auth_token)

    def new_from_pretrained(name: str, token: str | None = None) -> tuple[str, None]:
        return (name, None)  # BUG: token is silently dropped

    result = check_deprecation_window_differential(
        old_call=old_from_pretrained,
        new_call=new_from_pretrained,
        old_param="use_auth_token",
        new_param="token",
        shared_params=["name"],
    )
    assert result.passed is False
    assert result.failing_example is not None


def test_deprecation_window_differential_catches_a_mutant_with_inverted_boolean_semantics() -> None:
    def old_call(host: str, no_cuda: bool = False) -> tuple[str, bool]:
        return (host, no_cuda)

    def new_call_inverted(host: str, use_cpu: bool = False) -> tuple[str, bool]:
        return (host, not use_cpu)  # BUG: inverted

    result = check_deprecation_window_differential(
        old_call=old_call,
        new_call=new_call_inverted,
        old_param="no_cuda",
        new_param="use_cpu",
        shared_params=["host"],
    )
    assert result.passed is False


# --- ORACLE_SIGNATURE_CHECK ---------------------------------------------------------------------------


def test_oracle_signature_check_passes_when_the_record_matches_the_real_signature() -> None:
    record = _use_auth_token_record()

    def new_from_pretrained(name: str, token: str | None = None, revision: str = "main") -> None:
        return None

    result = check_oracle_signature(record, new_from_pretrained)
    assert result.passed is True
    assert result.tier == VerificationTier.ORACLE_SIGNATURE_CHECK


def test_oracle_signature_check_catches_a_mutant_where_the_claimed_parameter_does_not_exist() -> None:
    """Mutant: the KnowledgeRecord claims the new parameter is `token`, but the real installed signature
    actually calls it something else — e.g. a griffe-correlation false positive, or a stale record."""
    record = _use_auth_token_record()

    def wrong_signature(name: str, auth_token: str | None = None) -> None:  # not `token`
        return None

    result = check_oracle_signature(record, wrong_signature)
    assert result.passed is False


def test_oracle_signature_check_on_whole_symbol_rename_passes_when_new_symbol_resolved() -> None:
    record = KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.AutoModelForVision2Seq",
        new_symbol="transformers.AutoModelForImageTextToText",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.93,
    )

    def resolved_new_symbol(x: int) -> int:
        return x

    result = check_oracle_signature(record, resolved_new_symbol)
    assert result.passed is True


def test_oracle_signature_check_on_record_with_no_checkable_remapping_reports_honestly() -> None:
    """A REMOVED_NO_REPLACEMENT record has nothing an oracle check can verify — must say so plainly rather
    than silently pass or crash."""
    record = KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.AutoModelWithLMHead",
        new_symbol=None,
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.REMOVED_NO_REPLACEMENT,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.9,
    )
    result = check_oracle_signature(record, lambda: None)
    assert result.passed is False
    assert "nothing to verify" in result.reason


# --- COMPILE_CHECK -------------------------------------------------------------------------------------


def test_compile_check_result_is_trivially_true() -> None:
    result = compile_check_result()
    assert result.passed is True
    assert result.tier == VerificationTier.COMPILE_CHECK
