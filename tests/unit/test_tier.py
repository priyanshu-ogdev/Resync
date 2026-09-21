"""Unit tests for verification/tier.py's select_tier routing."""

from __future__ import annotations

from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType
from resync.patch.taxonomy import PatchStrategy
from resync.verification.tier import (
    VerificationTier,
    evaluate_record_verification,
    resolve_callable,
    select_tier,
)


def _rename_record(parameter: str = "no_cuda", new_parameter: str = "use_cpu") -> KnowledgeRecord:
    return KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.TrainingArguments",
        new_symbol="transformers.TrainingArguments",
        parameter=parameter,
        new_parameter=new_parameter,
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.95,
    )


def test_mechanical_rename_without_old_callable_gets_compile_check() -> None:
    record = _rename_record()
    tier = select_tier(record, PatchStrategy.MECHANICAL, old_callable=None)
    assert tier == VerificationTier.COMPILE_CHECK


def test_mechanical_rename_with_old_parameter_still_binding_upgrades_to_differential() -> None:
    record = _rename_record()

    def old_call(no_cuda: bool = False) -> bool:
        return no_cuda

    tier = select_tier(record, PatchStrategy.MECHANICAL, old_callable=old_call)
    assert tier == VerificationTier.DEPRECATION_WINDOW_DIFFERENTIAL


def test_mechanical_rename_with_old_parameter_absent_stays_compile_check() -> None:
    """The old parameter was already hard-removed — old_callable exists but doesn't accept it anymore, so
    the upgrade to the differential tier must not fire (it would try to call something that can't work)."""
    record = _rename_record()

    def old_call(use_cpu: bool = False) -> bool:  # already renamed, old kwarg doesn't exist
        return use_cpu

    tier = select_tier(record, PatchStrategy.MECHANICAL, old_callable=old_call)
    assert tier == VerificationTier.COMPILE_CHECK


def test_mechanical_reorder_gets_compile_check() -> None:
    record = KnowledgeRecord(
        package="netlib",
        ecosystem="pypi",
        old_symbol="netlib.connect",
        new_symbol="netlib.connect",
        old_param_order=["host", "port"],
        new_param_order=["port", "host"],
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.REORDER,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.95,
    )
    assert select_tier(record, PatchStrategy.MECHANICAL) == VerificationTier.COMPILE_CHECK


def test_semantic_strategy_always_gets_generator_critic_regardless_of_rule_type() -> None:
    record = _rename_record()
    assert select_tier(record, PatchStrategy.SEMANTIC) == VerificationTier.GENERATOR_CRITIC


def test_escalate_strategy_gets_oracle_signature_check() -> None:
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
    assert select_tier(record, PatchStrategy.ESCALATE) == VerificationTier.ORACLE_SIGNATURE_CHECK


def test_old_callable_with_uninspectable_signature_does_not_crash_and_falls_back_safely() -> None:
    """Some real callables (C extensions, certain decorators) have no inspectable signature at all — this
    must fail safe toward the weaker tier, not raise."""
    record = _rename_record()
    tier = select_tier(record, PatchStrategy.MECHANICAL, old_callable=len)  # builtin, often uninspectable-ish
    assert tier in (VerificationTier.COMPILE_CHECK, VerificationTier.DEPRECATION_WINDOW_DIFFERENTIAL)


def test_resolve_callable_resolves_standard_function() -> None:
    import json

    fn = resolve_callable("json.loads")
    assert fn is json.loads


def test_resolve_callable_returns_none_for_nonexistent() -> None:
    assert resolve_callable("nonexistent_package_xyz.foo") is None
    assert resolve_callable(None) is None


def test_evaluate_record_verification_returns_tier_and_result() -> None:
    record = _rename_record()
    tier, diff_res = evaluate_record_verification(record, PatchStrategy.MECHANICAL)
    assert tier == VerificationTier.COMPILE_CHECK
    assert diff_res.passed is True
    assert diff_res.tier == VerificationTier.COMPILE_CHECK
