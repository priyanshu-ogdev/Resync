# `tests/`

- `unit/` — one test module per `src/resync/` component, exercising the pure logic (taxonomy classification,
  config parsing, trust-score decomposition) without external services.
- `integration/` — exercises the real MCP server, a real (small, local) LanceDB/graph index, and the ast-grep
  binary together.
- `fixtures/` — real, small repos with known, deliberately introduced breaking changes, used by both unit and
  integration tests. The flagship set should include a `peft`/`bitsandbytes` combination matching the demo
  scenario in `docs/architecture.md#flagship-demo`.

Any change to `verification/` should come with a Hypothesis-based property test, not just a fixed-input unit
test — see `docs/adr/0002-differential-equivalence-verification.md` for why a single happy-path test isn't
sufficient evidence for this specific layer.
