# Product Requirements Document — Resync

This document is the *what and why*. `docs/architecture.md` (aliased as `docs/design.md`) is the *how*. If
the two ever disagree, that's a bug in one of them — flag it, don't quietly pick one.

## Problem statement

Two failure modes motivate this project, detailed in full with citations in `docs/architecture.md#the-problem`:

1. **Old code rots.** Libraries deprecate and remove APIs; codebases accumulate calls into functions no
   longer present in the pinned version. Flagship example: `peft`/`bitsandbytes`/`transformers`/`torch`
   version incompatibilities — one of the most common failure classes in ML development.
2. **New code is born broken.** AI coding agents hallucinate package names and deprecated API calls at
   measured, documented rates (research term: "slopsquatting" — see `docs/architecture.md` for citations).

No existing tool treats these as the same problem and fixes both directions — see
`docs/competitive-landscape.md` for what was reviewed and rejected as insufficient.

## Target users

- **Individual developers on an ML/AI Python stack** who hit dependency-version breakage regularly — the
  flagship demo persona.
- **Teams running AI coding agents** (Claude Code, OpenCode, Google Antigravity) against a shared codebase,
  who want agent-authored code checked against the actual pinned lockfile before it lands, not after.
- **Maintainers of brownfield repos** with accumulated deprecation debt who want it triaged and fixed with
  evidence, not just flagged.

Explicitly not the target for v0.1.0: teams needing full multi-language coverage (Python is the only shipped
adapter — see `docs/multi-language-adapters.md` for the designed-but-not-built roadmap), and a **hosted,
multi-tenant** SaaS deployment serving many unrelated organizations from one shared instance with billing and
tenant isolation. That's a different property from **horizontal scaling of one team's own self-hosted
deployment** (Phase 8, `docs/implementation-plan.md`), which *is* in scope — running multiple replicas of
one team's server behind a load balancer for that team's own throughput and reliability needs, with no
customer-isolation or billing concerns, is a natural consequence of the stateless MCP architecture
(`docs/adr/0001`) already chosen. Conflating these two would be a real scope-creep risk worth naming
explicitly rather than leaving implicit.

## Goals and success criteria

| Goal | How it's measured | Status |
|---|---|---|
| Real-time prevention: block an agent from writing a known-bad import/call | MCP gate integration test against a live agent session | Not yet built — Phase 4 |
| Scheduled correction: detect and fix drift in an existing repo | End-to-end fixture test (detect → retrieve → patch → verify) | Partially built — Phases 1–2 done, Phase 3 (verification) and Phase 5 (Python adapter completion) not yet |
| Mechanical fixes never touch the LLM | `patch/taxonomy.py` classification + `patch/ast_grep_runner.py` | **Met**, for both RENAME and REORDER. REORDER's unattended-scheduling gap is closed by the applied-already ledger (`config.schema.AppliedFix`, `ast_grep_runner.apply(..., repo_root=...)`) — a caller that always passes `repo_root` gets safe repeated application; the underlying ast-grep pattern is still not idempotent on its own by design (see that module's docstring), the guard lives one layer up |
| No fix ships without evidence of correctness | Differential/property-based equivalence layer | **Met, for three of the four tiers**: `verification/tier.py`/`differential.py`/`trust_score.py` implement compile-check, deprecation-window-differential, and oracle-signature-check, all with passing tests including deliberately-broken mutant cases the layer must reject. The fourth tier, `GENERATOR_CRITIC` (for LLM-drafted/semantic patches), has only its `Protocol` seam built — Phase 6's dependency for a concrete implementation |
| Knowledge base contains only verified facts, never fabricated ones | `knowledge/seed_data.py`'s discipline, enforced by `tests/unit/test_seed_data.py`; automated verified extraction via `knowledge/extract_api_diff.py` | **Met, and no longer manual-only** — 14 hand-curated records (up from 2), plus a real `griffe`-backed structural-diff adapter (`RecordSource.API_DIFF_TOOL`) that derives records from an actual AST diff between two package versions rather than transcribed prose. Still short of the ~30–50-record target and still `transformers`-only — see Known Gaps |
| Horizontal scaling with no architectural redesign | Multiple MCP server instances behind a load balancer, measured latency under concurrent load | Not yet built — Phase 8. Grounded in a decision already made (Phase 4/ADR 0001's stateless MCP core), not a new design |
| Shipped and installable | `pip install resync-mcp` succeeds from a clean environment; flagship demo runs end to end | Not yet built — Phase 9 |

## Requirements

### Functional
- FR1: Given a package and a pinned version, verify whether a symbol exists and is not deprecated
  (`server/tools.py::check_symbol_exists` — interface built, Phase 4 wiring not complete).
- FR2: Given a known API change, classify it as mechanical, semantic, or requiring escalation
  (`patch/taxonomy.py` — **built and tested**).
- FR3: Apply a mechanical fix without an LLM call and without corrupting unrelated code
  (`patch/ast_grep_runner.py` — **built and tested**, including regression coverage for a real data-loss bug
  found and fixed during implementation).
- FR4: Persist a project's pins, exceptions, and sync-vs-shift policy decisions across runs (`resync.toml`,
  `config/schema.py` + `config/loader.py` — **built and tested**).
- FR5: Retrieve the correct knowledge record for a query via the cheapest sufficient path (`knowledge/router.py`
  + `knowledge/query.py` — **built and tested**).
- FR6: Verify a proposed patch's correctness at a tier appropriate to its risk, not just "the tests passed"
  (`verification/tier.py` + `verification/differential.py` + `verification/trust_score.py` — **built and
  tested** for three of four tiers; see the Goals table above for the fourth, Phase-6-dependent tier).

### Non-functional
- NFR1: The real-time gate must return before the calling agent's next token — target p95 < 200ms
  (`docs/testing-strategy.md`). **Not yet measured** — no load test exists yet.
- NFR2: Runs entirely on 6–12GB VRAM locally, no mandatory cloud API call (`docs/tech-stack.md`). **Partially
  verified** — the knowledge-server dependency chain was confirmed to have zero `torch` dependency; a live
  local-model inference run has not been executed in this development environment.
- NFR3: Every dependency choice is checked for current maintenance health, not just technical fit
  (`docs/adr/0004` — the Kùzu-fork decision exists because of this requirement, not despite it).
- NFR4: The server scales horizontally (multiple instances behind a load balancer, no shared in-process
  state) without an architectural redesign. **Grounded, not assumed**: this is a direct consequence of
  building against MCP's 2026-07-28 stateless core (`docs/adr/0001`), whose specification change was
  explicitly motivated by removing the horizontal-scaling barrier of the prior session-based protocol — see
  `docs/implementation-plan.md`'s Phase 8 for the full research and the operational work still required to
  realize it. **Not yet built or measured** — Phase 4 and Phase 8.

## Explicit scope boundaries (not oversights)

Documented in place rather than only here, so a reader hits the caveat exactly where the relevant code is:
aliased imports, star imports, and bare module-attribute access are not handled mechanically
(`patch/ast_grep_runner.py`); the namesake-collision safety check cannot detect local shadowing of an
otherwise-valid import; TypeScript and Rust adapters are designed but not implemented;
`knowledge/extract_api_diff.py`'s rename-correlation is a name-similarity heuristic (margin-checked against
the runner-up, not just an absolute floor) that will miss semantically-related renames with unrelated
spellings and correctly falls back to `REMOVED_NO_REPLACEMENT` rather than guess — it has not been run
end-to-end against a real package pair in this development environment (no network access to install
`griffe` here), only integration-tested against `griffe`'s own repo diffed against itself as an API-plumbing
smoke test; a real `transformers`/`peft`/`bitsandbytes`/`torch` version-pair run, and eyeballing its output
before trusting it into the seed set, is real work still to do, not assumed complete. `verification/`'s
differential/oracle tiers verify call-compatibility and argument-forwarding equivalence, not deep numerical
equivalence of what an ML library actually computes (`verification/differential.py`'s module docstring) —
that's the library's own correctness contract, out of scope by design, not an oversight; `verification/
sandbox.py`'s two isolation backends are implemented and unit-tested at the dispatch level only, with no live
isolated execution run in this development environment (no network for `sandbox-runtime`, no local Docker
+gVisor here); and the `GENERATOR_CRITIC` tier (`verification/critic.py`) is a `Protocol` seam only — Phase
6's dependency for a concrete, model-backed implementation.

## Open questions

- Should the real-time gate's registry/advisory lookups be cached, and for how long, given package-yank
  events need to invalidate a cache quickly? Not yet decided — relevant once Phase 4 is built.
- ~~Does the differential-equivalence layer's property-based test generation need per-type strategies beyond
  what Hypothesis infers automatically for common signatures?~~ **Answered, by building and testing it**: yes,
  two things beyond bare `st.from_type` inference were needed — a fixed-corpus fallback for parameters with
  no usable annotation (`Any`/missing), and resolving annotations via `typing.get_type_hints` rather than
  reading them straight off `inspect.signature`, since the latter leaves them as unevaluated strings under
  `from __future__ import annotations` (a real bug this project's own test suite caught on first run — see
  `docs/implementation-plan.md`'s Phase 3 entry).

## Related documents

`docs/architecture.md` (design/how), `docs/workflow.md` (runtime flow), `docs/implementation-plan.md`
(phased build status), `docs/testing-strategy.md`, `docs/release-plan.md`, `docs/ui-design.md`,
`docs/research-foundations.md`, `docs/competitive-landscape.md`, `docs/tech-stack.md`,
`docs/multi-language-adapters.md`, `docs/adr/`.
