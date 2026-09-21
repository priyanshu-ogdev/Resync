"""The decomposed trust score.

Per docs/architecture.md#decision-2: a passing test suite is necessary but never
sufficient on its own. Every proposed change carries all four signals below, returned as structured MCP tool
output (not a text blob) so a calling agent or a review dashboard can act on the components programmatically
rather than trusting a single opaque number.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from resync.knowledge.schema import KnowledgeRecord
from resync.verification.critic import CriticVerdict
from resync.verification.differential import DifferentialResult
from resync.verification.tier import VerificationTier


class TrustScore(BaseModel):
    static_rule_match: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence from the signature-change taxonomy classification alone.",
    )
    test_suite_passed: bool = Field(
        description="Necessary, not sufficient — see docs/architecture.md#decision-2. Never gate solely on this."
    )
    differential_equivalence_passed: bool | None = Field(
        default=None,
        description="None if not applicable (e.g. a mechanical rename needs only a compile check).",
    )
    critic_pass_approved: bool | None = Field(
        default=None,
        description="Set only for LLM-drafted (semantic) patches — the generator/critic double-pass "
        "from docs/architecture.md#decision-2, modeled on LADU's Summary/Control/Code split.",
    )

    @property
    def overall(self) -> float:
        """A single number for quick sorting/filtering — never the sole basis for auto-apply decisions.

        `resync.toml`'s confidence thresholds should be checked against the decomposed fields directly for
        anything semantic; this property exists for dashboards and PR summaries, not gating logic.
        """
        if not self.test_suite_passed:
            return 0.0
        signals = [self.static_rule_match]
        if self.differential_equivalence_passed is not None:
            signals.append(1.0 if self.differential_equivalence_passed else 0.0)
        if self.critic_pass_approved is not None:
            signals.append(1.0 if self.critic_pass_approved else 0.0)
        return sum(signals) / len(signals)


def build_trust_score(
    record: KnowledgeRecord,
    test_suite_passed: bool,
    differential_result: DifferentialResult | None = None,
    critic_verdict: CriticVerdict | None = None,
) -> TrustScore:
    """The real wiring this phase adds: assembles a TrustScore from actual signals rather than leaving the
    model an untested shape someone has to remember to populate correctly by hand at every call site.

    `differential_result=None` is valid and expected for the COMPILE_CHECK tier specifically — see
    `differential.compile_check_result()`'s own docstring for why that tier's "check" is trivial by
    construction and callers may reasonably skip calling it at all; this function treats that omission the
    same as an explicit COMPILE_CHECK result (`differential_equivalence_passed` stays `None`), not as a
    missing/failed check.
    """
    differential_equivalence_passed: bool | None = None
    if differential_result is not None and differential_result.tier != VerificationTier.COMPILE_CHECK:
        differential_equivalence_passed = differential_result.passed

    return TrustScore(
        static_rule_match=record.confidence,
        test_suite_passed=test_suite_passed,
        differential_equivalence_passed=differential_equivalence_passed,
        critic_pass_approved=critic_verdict.approved if critic_verdict is not None else None,
    )
