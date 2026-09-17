"""Phase 3.4's seam, not its implementation: the generator/critic double-pass from
docs/adr/0002-differential-equivalence-verification.md is for LLM-drafted (semantic) patches and needs a
local model — Phase 6's dependency, not Phase 3's. What Phase 3 needs now is somewhere concrete for
`TrustScore.critic_pass_approved` to eventually get populated from, so that wiring isn't deferred whole and
`verification/tier.py`'s `VerificationTier.GENERATOR_CRITIC` isn't a dead end with nothing to call.

Modeled on LADU's Summary/Control/Code agent split (cited in ADR 0002): the critic's job is specifically
adversarial — it must actively find a reason a patch is wrong before it counts as approved, not simply agree
with the generator that drafted it. `CriticVerdict.approved=True` without at least one populated
`concerns_considered` entry should be treated with suspicion by any future caller — an approval that didn't
consider any way the patch could be wrong isn't the adversarial pass ADR 0002 calls for, it's a rubber stamp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class VerificationContext:
    """Everything a critic needs to review a patch, without needing to re-derive it from scratch."""

    old_source: str
    new_source: str
    knowledge_record_summary: str
    """A short natural-language summary of the KnowledgeRecord the patch is based on — not the full record
    object, deliberately: the critic should reason about what changed and why, not pattern-match on schema
    field names."""
    differential_result_summary: str | None = None
    """Summary of any COMPILE_CHECK/ORACLE_SIGNATURE_CHECK/DEPRECATION_WINDOW_DIFFERENTIAL result already
    computed for this patch (verification/differential.py), when available — the critic should have access
    to that evidence, not review in a vacuum."""


@dataclass
class CriticVerdict:
    approved: bool
    concerns_considered: list[str] = field(default_factory=list)
    """What the critic actively checked for and ruled out — the adversarial record itself, per this module's
    docstring. An empty list alongside approved=True is the rubber-stamp failure mode this field exists to
    make visible, not hide."""
    rejection_reason: str | None = None


class Critic(Protocol):
    """The Protocol Phase 6's concrete local-model-backed critic will implement. Kept minimal and
    synchronous-shaped here deliberately — Phase 6 owns the decision of whether its real implementation is
    async, batched, or otherwise more elaborate; this seam only needs to be stable enough for Phase 3's
    TrustScore wiring to compile against today.
    """

    def review(self, patch: Any, context: VerificationContext) -> CriticVerdict:
        """`patch` is intentionally typed `Any` here rather than a specific patch-representation type: that
        type doesn't exist yet in this codebase (semantic/LLM-drafted patches aren't generated until Phase
        6), and guessing its shape now risks locking in a wrong one. Tightening this signature once Phase 6
        actually defines that type is expected, not a sign this Protocol was wrong to add early.
        """
        ...
