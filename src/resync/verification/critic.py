"""Phase 3.4's seam, not its implementation: the generator/critic double-pass from
docs/architecture.md#decision-2 is for LLM-drafted (semantic) patches and needs a
local model — Phase 6's dependency, not Phase 3's. What Phase 3 needs now is somewhere concrete for
`TrustScore.critic_pass_approved` to eventually get populated from, so that wiring isn't deferred whole and
`verification/tier.py`'s `VerificationTier.GENERATOR_CRITIC` isn't a dead end with nothing to call.

Modeled on LADU's Summary/Control/Code agent split (cited in Decision 2, docs/architecture.md#decision-2):
the critic's job is specifically adversarial — it must actively find a reason a patch is wrong before it counts
as approved, not simply agree with the generator that drafted it. `CriticVerdict.approved=True` without at least one
populated `concerns_considered` entry should be treated with suspicion by any future caller — an approval that didn't
consider any way the patch could be wrong isn't the adversarial pass Decision 2 calls for, it's a rubber stamp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


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


class LlamaServerCritic:
    """Phase 6's concrete `Critic`: the adversarial review pass, over the same local `llama-server` process
    `llm/generator.py` uses to draft the patch — a genuinely different model *call* (a different prompt,
    asking it to find problems, not to write code), not a different model or a rubber-stamped re-ask of
    "does this look right?" which would defeat the whole point of a separate critic pass (ADR 0002, this
    module's docstring).

    `patch` is expected to be a `llm.generator.GeneratedPatch` — the concrete type this Protocol's own
    docstring anticipated would eventually exist. Duck-typed via `.content`/`.raw_response` rather than a
    hard import of `llm.generator`, so `verification/` (Phase 3) still doesn't need to depend on `llm/`
    (Phase 6) at import time — the dependency direction ADR 0002's phasing implies (verification is generic;
    the local model is one specific way to produce something for it to verify) stays intact.
    """

    def __init__(self, base_url: str, *, model: str = "default", client: httpx.Client | None = None) -> None:
        self._base_url = base_url
        self._model = model
        self._client = client

    def review(self, patch: Any, context: VerificationContext) -> CriticVerdict:
        content = getattr(patch, "content", None)
        if content is None:
            raise TypeError(
                "LlamaServerCritic.review() expects a patch object with a `.content` attribute "
                "(e.g. llm.generator.GeneratedPatch) — got " + type(patch).__name__
            )
        if content == "UNABLE_TO_DRAFT":
            return CriticVerdict(
                approved=False,
                concerns_considered=["the generator itself declined to draft a patch"],
                rejection_reason="no draft was produced to review",
            )

        owns_client = self._client is None
        http_client = self._client or httpx.Client(timeout=120.0)
        try:
            try:
                response = http_client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json={
                        "model": self._model,
                        "temperature": 0.1,
                        "messages": [
                            {"role": "system", "content": _CRITIC_SYSTEM_PROMPT},
                            {"role": "user", "content": _build_review_prompt(content, context)},
                        ],
                    },
                )
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                # A critic that can't be reached must never silently default to approved — that would make
                # an outage indistinguishable from a real review, exactly backwards for an adversarial gate.
                return CriticVerdict(
                    approved=False,
                    concerns_considered=[],
                    rejection_reason=f"the critic model could not be reached or returned an unusable "
                    f"response — treated as not approved, not silently passed: {exc}",
                )
        finally:
            if owns_client:
                http_client.close()

        return _parse_critic_response(message)


_CRITIC_SYSTEM_PROMPT = """You are an adversarial code reviewer. You will be given a known API change, the
original file, and a proposed rewrite. Your job is to find reasons the rewrite might be WRONG — do not simply
agree with it. Consider: did it change anything beyond what the known change requires? Could the rewrite
break at runtime? Does it handle all call sites, not just the first one?

Respond in exactly this format, nothing else:
CONCERNS: <comma-separated list of specific things you checked, even if you found no problem with them —
  an empty list is not acceptable>
VERDICT: APPROVE or REJECT
REASON: <if REJECT, why. If APPROVE, leave blank>
"""


def _build_review_prompt(content: str, context: VerificationContext) -> str:
    parts = [
        f"Known change:\n{context.knowledge_record_summary}",
        f"Original file:\n{context.old_source}",
        f"Proposed rewrite:\n{content}",
    ]
    if context.differential_result_summary:
        parts.append(f"Automated verification already run:\n{context.differential_result_summary}")
    return "\n\n".join(parts)


def _parse_critic_response(message: str) -> CriticVerdict:
    """Deliberately strict, structured parsing rather than a fuzzy "does it contain the word approve"
    check — a false-positive parse of an ambiguous response is exactly the rubber-stamp failure mode this
    whole module exists to prevent. An unparseable response is a REJECT, not a best-effort guess.
    """
    concerns: list[str] = []
    verdict: str | None = None
    reason: str | None = None
    for line in message.splitlines():
        line = line.strip()
        if line.upper().startswith("CONCERNS:"):
            concerns = [c.strip() for c in line.split(":", 1)[1].split(",") if c.strip()]
        elif line.upper().startswith("VERDICT:"):
            verdict = line.split(":", 1)[1].strip().upper()
        elif line.upper().startswith("REASON:"):
            reason = line.split(":", 1)[1].strip() or None

    if verdict == "APPROVE" and concerns:
        return CriticVerdict(approved=True, concerns_considered=concerns)
    if verdict == "APPROVE" and not concerns:
        # The exact rubber-stamp shape this module's docstring warns about — treat as untrustworthy rather
        # than pass it through.
        return CriticVerdict(
            approved=False,
            concerns_considered=[],
            rejection_reason="model said APPROVE but listed no concerns considered — treated as an "
            "unreliable rubber-stamp response, not a genuine adversarial review",
        )
    return CriticVerdict(
        approved=False,
        concerns_considered=concerns,
        rejection_reason=reason or f"could not parse an APPROVE verdict from the model's response: {message!r}",
    )
