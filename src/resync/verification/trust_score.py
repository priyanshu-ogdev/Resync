"""The decomposed trust score.

Per docs/adr/0002-differential-equivalence-verification.md: a passing test suite is necessary but never
sufficient on its own. Every proposed change carries all four signals below, returned as structured MCP tool
output (not a text blob) so a calling agent or a review dashboard can act on the components programmatically
rather than trusting a single opaque number.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TrustScore(BaseModel):
    static_rule_match: float = Field(
        ge=0.0, le=1.0, description="Confidence from the signature-change taxonomy classification alone."
    )
    test_suite_passed: bool = Field(
        description="Necessary, not sufficient — see docs/adr/0002. Never gate solely on this."
    )
    differential_equivalence_passed: bool | None = Field(
        default=None,
        description="None if not applicable (e.g. a mechanical rename needs only a compile check).",
    )
    critic_pass_approved: bool | None = Field(
        default=None,
        description="Set only for LLM-drafted (semantic) patches — the generator/critic double-pass "
        "from docs/adr/0002, modeled on LADU's Summary/Control/Code split.",
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
