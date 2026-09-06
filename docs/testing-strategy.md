# Testing strategy

Testing this project is unusually load-bearing: the entire premise of `docs/adr/0002-differential-equivalence-verification.md`
is that a naive test-suite-passed signal is not trustworthy, so the tests *of* Resync's verification layer
itself need to be held to a higher standard than "the happy path works." This document is that standard,
covering both how each component of `docs/architecture.md` should be tested and how the project verifies
itself.

## The testing pyramid, mapped to this project's specific risk profile

1. **Unit tests** — one module per `src/resync/` component (`config`, `knowledge`, `patch`, `verification`,
   `adapters`), exercising pure logic with no external services. `ResyncConfig.is_pinned_or_frozen` and
   `TrustScore.overall` are exactly the kind of small, correctness-critical functions that deserve
   table-driven unit tests covering every branch, not just the obvious case.

2. **Property-based tests (Hypothesis)** — not only used *by* the verification layer, but *of* it. The
   `RuleType` classifier, `TrustScore` decomposition, and `ResyncConfig` parsing should all have Hypothesis
   tests generating adversarial inputs (malformed `resync.toml`, contradictory pin/exception overlaps,
   out-of-range confidence values) rather than only hand-picked examples. Testing the tester with the same
   technique it uses on target code is deliberate, not decorative.

3. **Integration tests** — the real `ast-grep` binary, a real (small) LanceDB/graph index, and a real MCP
   server process talking over stdio, run together against `tests/fixtures` repos. Mocking any of these away
   defeats the point: this project's central claim is that these specific tools compose correctly.

4. **End-to-end demo-regression tests** — the flagship scenario from `docs/architecture.md#flagship-demo`
   (a real repo pinned to a known-broken `peft`/`bitsandbytes` combination) automated as a CI check, not just a
   manually rehearsed script. If the demo can silently break between commits, it will, right before it matters
   most.

5. **Adversarial and robustness testing** — intentionally malformed `resync.toml` files, package names crafted
   to look like known-good packages (the slopsquatting pattern this project exists to catch — see
   `docs/architecture.md#the-problem`), and basic sandbox-escape attempts against whichever sandbox
   (`sandbox-runtime` or the Docker+gVisor fallback) is in use. A tool whose entire purpose is catching
   supply-chain and correctness attacks should be tested against those attack shapes directly, not assumed
   safe by construction.

6. **Latency budget tests** — the real-time gate (`server/tools.py`) has an explicit, stated requirement in
   `docs/architecture.md#two-speeds`: it must return before the calling agent's next token. Define this as a
   real, checked number (target: p95 under 200ms for `verify_package`/`check_symbol_exists` against a warm
   local index) and fail CI if it regresses, rather than leaving "fast" as an unverified adjective.

## Coverage targets

- **Verification layer (`verification/`):** the highest bar in the codebase — target 100% branch coverage.
  This is the module whose entire job is catching correctness regressions elsewhere; it cannot be the place
  correctness regressions hide.
- **Config and knowledge schemas:** 100% — these are small, pure, and every branch is cheap to cover.
- **Everything else:** 80% as a floor, enforced in CI via `pytest-cov`, not treated as an aspirational number.

## Verifying the release itself

Before tagging a release, run Resync's own supply-chain provenance gate (`docs/architecture.md#supply-chain-provenance-gate`)
against its own dependency tree — the project should be able to say, honestly, that it applied its own
standard to itself. Combine this with `uv`'s lockfile audit and a manual review of anything the OpenAI/Astral
acquisition watch item (`docs/tech-stack.md`) might affect between releases.

## What this project does not do

It does not chase 100% coverage everywhere as a vanity metric — `cli/main.py`'s thin command wrappers and
per-adapter glue code are appropriately covered by the integration and end-to-end layers rather than
exhaustive unit tests of every line. Coverage numbers are a tool for finding untested risk, not a target to
game.
