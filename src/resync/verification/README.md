# `verification/`

The trust and verification layer — the component that exists specifically because "the tests passed" is not
proof of correctness. See `docs/adr/0002-differential-equivalence-verification.md` for the research this is
built on (19–35% functional non-equivalence in LLM-generated refactorings, ~21% test-suite escape rate).

- `trust_score.py` — `TrustScore`, the decomposed, structured signal set (static rule match, test pass,
  differential-equivalence pass, generator/critic pass) returned as MCP structured output.

The differential/property-based equivalence engine (Hypothesis-driven input generation, side-by-side old/new
execution) and the sandbox wrapper (`sandbox-runtime`, with Docker+gVisor as a documented fallback given its
experimental status — see `docs/tech-stack.md`) belong here once built.
