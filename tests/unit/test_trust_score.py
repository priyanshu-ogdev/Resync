"""Unit tests for verification/trust_score.py's build_trust_score wiring."""

from __future__ import annotations

from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType
from resync.verification.critic import CriticVerdict
from resync.verification.differential import DifferentialResult
from resync.verification.tier import VerificationTier
from resync.verification.trust_score import build_trust_score


def _record(confidence: float = 0.9) -> KnowledgeRecord:
    return KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.TrainingArguments",
        new_symbol="transformers.TrainingArguments",
        parameter="no_cuda",
        new_parameter="use_cpu",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=confidence,
    )


def test_compile_check_tier_leaves_differential_field_none() -> None:
    """Per TrustScore's own field docstring: None means 'not applicable', which is exactly the
    COMPILE_CHECK tier's case — must not be conflated with a failed check."""
    result = DifferentialResult(tier=VerificationTier.COMPILE_CHECK, passed=True, reason="trivial")
    score = build_trust_score(_record(), test_suite_passed=True, differential_result=result)
    assert score.differential_equivalence_passed is None


def test_omitting_differential_result_entirely_behaves_the_same_as_compile_check() -> None:
    score = build_trust_score(_record(), test_suite_passed=True, differential_result=None)
    assert score.differential_equivalence_passed is None


def test_oracle_tier_result_populates_the_field() -> None:
    result = DifferentialResult(tier=VerificationTier.ORACLE_SIGNATURE_CHECK, passed=True, reason="ok")
    score = build_trust_score(_record(), test_suite_passed=True, differential_result=result)
    assert score.differential_equivalence_passed is True


def test_failed_differential_result_is_reflected_and_tanks_overall() -> None:
    result = DifferentialResult(tier=VerificationTier.DEPRECATION_WINDOW_DIFFERENTIAL, passed=False, reason="diverged")
    score = build_trust_score(_record(confidence=0.99), test_suite_passed=True, differential_result=result)
    assert score.differential_equivalence_passed is False
    assert score.overall < 0.99  # the failed differential check must actually drag the overall score down


def test_failing_test_suite_zeroes_overall_regardless_of_other_signals() -> None:
    result = DifferentialResult(tier=VerificationTier.DEPRECATION_WINDOW_DIFFERENTIAL, passed=True, reason="ok")
    score = build_trust_score(_record(confidence=0.99), test_suite_passed=False, differential_result=result)
    assert score.overall == 0.0


def test_critic_verdict_populates_critic_field() -> None:
    verdict = CriticVerdict(approved=True, concerns_considered=["checked null handling"])
    score = build_trust_score(_record(), test_suite_passed=True, critic_verdict=verdict)
    assert score.critic_pass_approved is True


def test_no_critic_verdict_leaves_field_none() -> None:
    score = build_trust_score(_record(), test_suite_passed=True)
    assert score.critic_pass_approved is None
