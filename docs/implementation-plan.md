# Implementation plan

This is the phased path from the current scaffold (typed interfaces, no working logic) to a demoable,
released v0.1.0. Each phase states its goal, deliverables, what it depends on, and — critically — its exit
criteria, so "done" is a checkable fact, not a feeling. Phases map directly onto the modules already scaffolded
under `src/resync/`; nothing here introduces a new component that isn't already justified in
`docs/architecture.md`.

## Phase 0 — Foundation (complete)

Scaffold, ADRs, the four research/landscape/tech-stack docs, and typed-but-unimplemented interfaces across
every module. Exit criteria already met: every Python file parses, every TOML file validates, the adapter
Protocol and knowledge-record schema are stable enough to build against.

## Phase 1 — Knowledge layer

**Goal:** a working hybrid retrieval store populated with real knowledge records for the flagship package set.

- Bind `KnowledgeRecord` (already defined) to a LanceDB table schema; implement insert/upsert.
- Stand up the graph index on the Kùzu fork (`docs/adr/0004`): `File` nodes, `IMPORTS` edges initially.
- Wire `fastembed` for chunk/record embedding (`docs/tech-stack.md` — no `torch` anywhere in this phase).
- Implement the adaptive router: a simple heuristic first (route on query shape — exact symbol lookup vs.
  free-text question), not a learned classifier. Do not over-build this; see `docs/research-foundations.md#1`
  for why a router exists at all, but a rule-based router is sufficient for v0.1.0.
- Populate real `KnowledgeRecord`s for `peft`, `bitsandbytes`, `transformers`, and `torch` across the specific
  version pairs the flagship demo needs, via changelog extraction and `ast`/`inspect` diffing.

**Depends on:** Phase 0. **Exit criteria:** a hand-built evaluation set of ~30–50 known API changes in the
target packages retrieves the correct `KnowledgeRecord` at ≥90% precision at k=1.

## Phase 2 — Deterministic patch layer

**Goal:** mechanical fixes apply correctly with zero LLM involvement.

- Wire `ast-grep` invocation via subprocess (binary dependency, not a Python binding — `docs/tech-stack.md`).
- Implement the `RuleType`-driven classifier deciding mechanical vs. semantic handling (the enum already
  exists in `knowledge/schema.py`; the classification logic belongs in `patch/taxonomy.py`).
- Generate ast-grep rules for `RENAME` and `REORDER` cases from a `KnowledgeRecord`.

**Depends on:** Phase 1 (needs real records to patch against). **Exit criteria:** mechanical fixes apply
correctly and idempotently (running twice produces no further diff) against the `tests/fixtures` repos.

## Phase 3 — Verification layer

**Goal:** every proposed patch is checked for behavioral equivalence, not just "the tests passed."

- Implement Hypothesis-based property test generation targeting a changed function's signature.
- Implement the differential execution harness: old vs. new code side by side where both are available,
  oracle-from-knowledge-record otherwise (`docs/adr/0002` — avoid the self-testing circularity).
- Wire `TrustScore` computation (already modeled) to real signals.
- Integrate `sandbox-runtime` for isolated execution, with a documented Docker+gVisor fallback given its
  experimental status (`docs/tech-stack.md`).

**Depends on:** Phase 2 (needs patches to verify). **Exit criteria:** on a labeled set of intentionally-correct
and intentionally-broken patches, the layer correctly flags every broken one (target: zero false negatives on
the labeled set — a false negative here is the exact failure mode this whole project exists to prevent).

## Phase 4 — MCP server and the real-time gate

**Goal:** an agent gets blocked or corrected before it commits to broken code.

- Implement `verify_package` (registry existence + OSV.dev/GitHub Advisory check).
- Implement `check_symbol_exists` for real (resync.toml pin/exception short-circuit already scaffolded in
  `server/tools.py`; wire the knowledge-store lookup behind it).
- Wire MCP transport: stdio first (simplest to test locally), then Streamable HTTP against the
  2026-07-28 stateless core (`docs/adr/0001`).
- Finalize and test the companion Skill (`skills/resync/SKILL.md`) against a real agent session.

**Depends on:** Phase 1 (knowledge lookups) and Phase 3's pin/exception logic. **Exit criteria:** a live Claude
Code or OpenCode session attempting a known-bad import or deprecated call is correctly blocked, with a
structured, actionable result — not a silent failure or a generic error.

## Phase 5 — Python adapter completion and provenance

**Goal:** the full detect → retrieve → patch → verify → provenance loop works end to end on a real repo.

- Implement `extract_api_diff` for Python (the hardest adapter — see
  `docs/multi-language-adapters.md#python`).
- Wire the resolver (`uv`, falling back to `pip-compile`/Poetry) for `resolve`.
- Implement the supply-chain provenance gate: OSV.dev, GitHub Advisory Database, Sigstore verification before
  any new version lands (`docs/architecture.md#supply-chain-provenance-gate`).

**Depends on:** Phases 1–3. **Exit criteria:** running the full loop against a `tests/fixtures` repo with a
known broken `peft`/`bitsandbytes` combination produces a correct, verified patch with no manual intervention.

## Phase 6 — CLI and local model integration

**Goal:** the offline-first surface actually works.

- Wire `llama-server` process lifecycle management (start, health check, stop) — run as its own process over
  an OpenAI-compatible HTTP endpoint, never in-process (`docs/tech-stack.md`).
- Implement `resync check`, `resync sync`, `resync serve` for real (currently `NotImplementedError` stubs in
  `cli/main.py`).
- Implement the generator/critic double-pass for semantic-tier patches using the local model.

**Depends on:** Phases 2, 3, 5. **Exit criteria:** `resync sync` run against a fixture repo completes the full
loop locally, using only the 6–12GB VRAM budget, with no cloud API calls.

## Phase 7 — Delivery and UI

**Goal:** output reaches a human in a form they can act on without reading logs.

- GitHub App scaffolding for brownfield PR delivery, sharded per `docs/architecture.md#the-impact-map` for
  large confirmed syncs. If the GitHub App review process doesn't fit the build timeline, fall back to a
  GitHub Actions-triggered bot using a fine-grained PAT — functionally equivalent for a demo, easier to stand
  up quickly, worth revisiting for a real release.
- PR comment template carrying the decomposed trust score (see `docs/ui-design.md`).
- The local review dashboard (`docs/ui-design.md`) for pending Impact Map decisions and recent-change history,
  served as additional routes on the same Starlette app already running for the MCP HTTP transport — no new
  web framework dependency.

**Depends on:** Phase 3 (trust scores to display), Phase 5.11-equivalent Impact Map work if that's in scope for
this milestone (it isn't — see the build-priority table in `docs/architecture.md`; the dashboard's "pending
decisions" view can ship against mocked data until the Impact Map itself is built, since the UI and the logic
it displays are separable work). **Exit criteria:** a PR opens with a correct, readable trust breakdown; the
dashboard renders real trust-score history from Phase 3's output.

## What stays out of this plan on purpose

TypeScript and Rust adapters, the Impact Map's live decision logic (as opposed to its UI shell), the public
breaking-change manifest standard, and DepMigrationBench are all designed in detail elsewhere
(`docs/multi-language-adapters.md`, `docs/architecture.md#the-impact-map`, `docs/architecture.md#roadmap`) but
are explicitly not phases in this plan. Adding them before Phases 0–7 are solid would repeat the exact scope
mistake flagged repeatedly during this project's design — see the "Any other upgrades" pattern in the design
history. Testing and release are covered separately in `docs/testing-strategy.md` and `docs/release-plan.md`.
