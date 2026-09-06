# ADR 0002: Verify patches with differential/property-based equivalence, not test-suite pass alone

**Status:** accepted

## Context

The default correctness signal for an automated code-fixing tool is "the existing test suite still passes."
This is what the closest reactive prior art, Google's Dependency Director, relies on entirely. Reviewing
current research, that signal is measurably insufficient: a 2026 study on LLM-generated refactorings found
19–35% were functionally non-equivalent to the original, and roughly 21% of those slipped past the project's
own existing test suite undetected. A separate 2026 study ("Articulate but Wrong") found LLMs are unreliable at
judging their own modernization output for exactly this kind of silent behavioral drift — so having the model
self-review its own patch is not a sufficient substitute either.

## Decision

Every proposed patch — mechanical or semantic — passes through a differential/property-based equivalence
check before it counts as verified: generate property-based test inputs (via Hypothesis) targeting the changed
function's signature, execute the old and new code paths side by side wherever both are available, and diff
actual outputs, not just check for the absence of exceptions. Where the old version can't run side-by-side,
generate the oracle from the retrieved API-diff/changelog knowledge record rather than from the legacy code
itself, to avoid the circularity of testing a translation against itself. Layer a generator/critic double-pass
on top for LLM-drafted (semantic) patches, mirroring the Summary/Control/Code agent split used in the LADU
research — an adversarial second pass that must actively find a reason a patch is wrong before it counts as
approved.

## Alternatives considered

- **Test-suite pass alone** — rejected, per the research above; this is Dependency Director's approach and the
  clearest technical gap between it and Resync.
- **LLM self-review only** — rejected; the "Articulate but Wrong" finding specifically shows this fails on the
  silent-drift case that matters most.
- **Formal verification of every patch** — considered and rejected as disproportionate; differential testing
  gives most of the practical benefit at a fraction of the engineering cost, and is tractable within the
  project's build timeline.

## Consequences

Every semantic-tier patch costs more compute and more wall-clock time than a bare test-suite run, since it
requires generating and executing property-based test inputs and, where applicable, running two versions of
the code side by side. This is deliberate: Section 4 of `docs/architecture.md` states this trade-off as a
non-negotiable design principle, not an optimization to revisit later. Mechanical fixes (taxonomy: rename,
reorder) are exempt from the heavier check since a compile check is sufficient for their risk profile — see
the signature-change taxonomy table in `docs/architecture.md`.

## References

- 2026 study on functional non-equivalence in LLM-generated refactorings (19–35% non-equivalent, ~21% test-suite
  escape rate).
- "Articulate but Wrong: Self-Review Failures in LLM-Based Code Modernization" (2026).
- LADU (LLM Agents for Automated Dependency Upgrades) — Summary/Control/Code agent architecture.
- Google's Dependency Director (July 2026) — the reactive prior art this decision differentiates against.
