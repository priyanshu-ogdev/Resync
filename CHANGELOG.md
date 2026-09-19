# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioning follows
[Semantic Versioning 2.0.0](https://semver.org/).

## [Unreleased]

### MCP client config generation — 8 real, verified formats via a declarative, scalable registry
`resync mcp-config` (new CLI command), `resync mcp-config-list`, and `resync mcp-config custom` — see
`docs/adr/0006-mcp-client-config-generation.md` for the full design account.

- Live research (2026-09) into each client's own current documentation and real bug trackers found **four
  genuinely different JSON shapes** across eight clients, not one shape with cosmetic differences: Claude
  Desktop/Claude Code/Cursor/Windsurf/Antigravity share `{"mcpServers": {...}}`; VS Code uses `{"servers":
  {...}}` with an *explicitly required* `type` field; OpenCode uses `{"mcp": {...}}` with a combined command
  array and `environment` (not `env`); Zed uses `{"context_servers": {...}}` with command/args *nested
  inside* a `command` object.
- Built as a declarative `ClientSpec` registry driving one generic `build_entry()` shape-interpreter, not
  per-client `if/elif` branches — adding a client (or fixing one that changed its format) is now a data
  change, not new control flow. `resync mcp-config-list` shows each entry's verification date and known
  caveats, since this module has no way to detect format drift on its own.
- `resync mcp-config custom --root-key ... --command-style ...` is a first-class escape hatch for any
  MCP-compliant agent not yet in the registry — usable immediately, no resync release required, since every
  compliant client accepts some command/args/env triple by definition of being MCP-compliant at all.
- Two real, currently-open client bugs found and designed around, not just noted: Claude Desktop deletes its
  entire `mcpServers` section on startup if it finds a `url`-based entry (never emitted for it, structurally
  — `ClientSpec.supports_url=False`); OpenCode's `environment` field is confirmed to sometimes not reach the
  spawned child process in practice.
- Antigravity's config path is deliberately never auto-written — live research found genuinely conflicting,
  version-dependent reports across its own Desktop/IDE/CLI surfaces; the command prints the (well-
  corroborated) JSON and points to Antigravity's own in-app config UI instead of guessing a path that might
  be wrong for a given install.
- Every write merges into the existing file (any other MCP servers or unrelated settings already present are
  left untouched) rather than overwriting it.
- 37 unit tests + 11 CLI-level integration tests, all against real file I/O and the real CLI entrypoint —
  including a real round-trip through Zed's nested-object shape and a real pre-existing-file merge.
- Wired into `resync init`'s next-steps panel for discoverability.
- Full sweep: **263/263 tests passing**, `ruff`/`mypy` clean across 43 source files.

### `verify_patch_equivalence` MCP tool, a branch merge, and Phase 7 redesigned around a terminal UI
- New MCP tool `verify_patch_equivalence` (`server/patch_verification.py`): lets a live agent session (any
  MCP client — Claude Code, opencode, Antigravity, or anything else speaking the protocol, no per-agent code
  needed) hand resync a self-drafted rewrite and get a real, deterministic check back, rather than trusting
  its own self-assessment. Deliberately scoped to static, execution-free AST checks in this version — running
  arbitrary agent-supplied code, even sandboxed, is real security-sensitive work deserving its own pass, not
  bolted on here. 10 unit tests plus MCP-protocol-level integration tests (in-process `call_tool` and real
  Streamable HTTP), all passing.
- Explicitly considered and rejected: shelling out to `claude`/`opencode`/other agent CLIs directly to borrow
  a live session's model. MCP is already the interoperability layer — every compliant client calls a tool
  identically regardless of which CLI or model is on the other end; building per-CLI subprocess adapters
  would mean tracking several independently-versioned external surfaces' own bugs for zero protocol benefit,
  and is architecturally backwards besides (those agents call *into* resync; spawning them back out is
  circular). Independently confirmed: MCP's Sampling feature (the protocol-native "ask the client's model"
  mechanism) is deprecated as of spec 2026-07-28 (SEP-2577) — new implementations should integrate directly
  with LLM provider APIs, which is exactly Phase 6's existing local-model design.
- **Merged real, independently-verified work from a separately-uploaded branch**: a more rigorous,
  lock-protected `_OutputDrainer` in `llm/llama_server.py` (superseding this session's own equivalent fix —
  both found the same real pipe-buffer deadlock independently, the merged version is simply more careful);
  a real fix in `verification/provenance.py` for PEP 740's four distinct publisher types (only two of which
  expose `.repository`); and a real fix tightening `sync --tier semantic`'s per-file gate from "imports the
  package at all" to "actually references the changed symbol" (reusing `cli/scan.py`'s existing AST-based
  resolution) — all reviewed and adopted after verifying them directly, not merged on trust.
- **In the other direction, restored real work that the uploaded branch was missing**:
  `tests/integration/test_streamable_http.py` (real, protocol-level Streamable HTTP tests — ASGI lifespan
  handling, DNS-rebinding protection) existed in an earlier line of work on this project and was genuinely
  verified then, but wasn't present in the uploaded branch. Recreated rather than silently lost in the merge.
- **Phase 7 redesigned, not just executed as originally planned**: the original plan called for a Starlette-
  served web dashboard. Reconsidered in favor of `resync init` — a genuinely interactive terminal setup
  wizard (`cli/init_wizard.py`), fitting this project's local-first design center better than standing up
  Jinja2 dashboard routes most users would open once. The web dashboard idea is deferred for a future
  shared/team deployment, not discarded. `resync init` writes `resync.toml` through a guided walkthrough
  (mode, target profile, auto-apply threshold, optional pins) and offers to seed the knowledge store
  immediately after; `--yes`/`--no-seed` keep it scriptable when that's what's actually needed.
  `check`/`sync`/`resolve`/`serve` stay exactly as non-interactive as before — a hard constraint this phase's
  UI work was not allowed to regress. 10 tests, all passing, driven through real simulated stdin (the actual
  interactive prompts are exercised, including non-default answers and the existing-config overwrite path).
- Full sweep after this pass: every file parses, every TOML validates, `ruff`/`mypy` clean (42 source files),
  **137/139 unit tests passing** (2 legitimate skips), **48/64 integration tests passing** (16 failures are
  all the same, already-documented missing-`ast-grep`-binary gap, unchanged in kind by this pass).

### Post-upload review: three real bugs found and fixed, none present in the prior session's own account
Independent review pass on an uploaded zip, following this project's established practice: treat an
accompanying narrative as an unverified claim, check the actual shipped code, not the story about it. Two
of the three bugs below turned out to be real work that a prior session's own transcript described doing
and verifying — but which was never actually present in the zip it produced. Re-implemented and
re-verified independently rather than trusted.

- **A real, reproduced deadlock in `llm/llama_server.py`, fixed**: `subprocess.Popen(..., stdout=PIPE,
  stderr=STDOUT)` had nothing draining that pipe while `_wait_until_healthy` polled — an OS pipe's buffer
  (~64KB on Linux) fills fast under llama.cpp's verbose model-loading logs, and once full, the child's next
  `write()` blocks forever. Confirmed the deadlock is real by directly reproducing it (a child writing
  200KB with no concurrent reader hangs past a 5s timeout), then fixed it with a background-thread
  `_OutputDrainer`, wired through `start()`/`_wait_until_healthy()`. New regression test genuinely proves
  the fix — not just that the code runs, but that the same reproduction now completes well within timeout.
- **A real mypy error in `verification/provenance.py`, fixed**: code assumed every PEP 740 publisher type
  exposes `.repository`, but confirmed live against the real installed `pypi_attestations` package that only
  `GitHubPublisher`/`GitLabPublisher` do — `GooglePublisher` has `.email`, `CircleCIPublisher` has
  `.project_id`/`.vcs_origin`. Fixed with a `_describe_publisher` helper covering all four real types.
- **A real, meaningful correctness/efficiency gap in `resync sync --tier semantic`, fixed**: the loop gated
  LLM calls on "does this file import the affected package at all" — far coarser than mechanical sync's
  actual per-symbol `ast-grep` matching. A file importing a package for an unrelated reason would still get
  sent to the local model to "draft a fix" for a symbol it never references — a wasted call, and a real risk
  of a spurious edit. Fixed using the already-built, AST-based `cli/scan.py::extract_fully_qualified_symbols`
  (resolves real import provenance, unlike a naive text search) as an additional gate. New regression test
  proves the generator is now only called for files that actually reference the changed symbol.
- Full sweep in this environment (real network, real `ast-grep` binary, real `pypi_attestations`/`sigstore`
  installed — a materially stronger verification environment than the prior no-network session that produced
  the uploaded zip): **189/189 tests passing**, `ruff`/`mypy` clean across 40 source files.

### Phase 6 — local model integration: llama-server lifecycle, generator/critic, `sync --tier semantic`
- New `llm/` package: `llama_server.py` (process lifecycle — start/health-poll/stop, CLI flags and `/health`
  shape verified against current real llama.cpp documentation before coding against them) and
  `generator.py` (`draft_patch()` over the real OpenAI-compatible `/v1/chat/completions` shape).
- `verification/critic.py` gained `LlamaServerCritic`, the concrete implementation of Phase 3's `Critic`
  Protocol seam. Genuinely adversarial by construction: an `APPROVE` verdict with zero listed concerns is
  parsed as **rejected**, not approved — the exact rubber-stamp failure mode that Protocol's own docstring
  warned about when it was first written, now enforced in code, not just prose. Every failure mode
  (unreachable model, malformed response, a declined `UNABLE_TO_DRAFT` draft) fails closed.
- `resync sync --tier semantic` implemented for real: starts its own `llama-server` for the sweep
  (guaranteed stopped via `try/finally`), reuses `ast_grep_runner._package_is_imported`'s existing
  import-guard safety check, and only ever writes a file the critic actually approved — `--apply` cannot
  override a rejection.
- 20 new tests across `llm/llama_server.py` (8), `llm/generator.py` (5), `verification/critic.py`'s new
  class (7), plus 3 CLI-level integration tests for `sync --tier semantic`.
- **A real regression found and fixed by running the existing suite**: `test_sync_cli.py`'s "tier not
  implemented" test asserted `--tier semantic` exits 2 — true before this phase, false after. Updated to
  target `--tier critical` (still genuinely unimplemented by design), rather than left asserting stale
  behavior.
- Full sweep: every file parses, every TOML validates, `ruff`/`mypy` clean (40 source files),
  **126/128 unit tests passing** (2 legitimate skips), **32/47 integration tests passing** (15 failures are
  all the same, already-documented missing-`ast-grep`-binary gap — unchanged in kind by this phase, just
  more surface area now depends on it — and 9 legitimate skips for unreachable-network cases).
- **Honestly still open**: no network access here to fetch a real `llama-server` binary or GGUF model, so
  the full loop has not run against a real local model — every component's mechanics are real and tested,
  but Phase 6's own exit criteria ("completes the full loop locally... with no cloud API calls") needs a
  real model present to fully close. See `docs/implementation-plan.md`'s Phase 6 entry for the precise
  account of what is and isn't verified.

### Independent verification pass, this session — one real classification gap and one real crash bug found and fixed
Uploaded as `v19` with an accompanying narrative describing prior work; that narrative was treated as
unverified, and everything below was independently re-checked in this session's own (network-disabled)
sandbox before being trusted.

- **`resolve/resolver.py`'s exit-code-only classification, verified against the real `uv` binary in this
  session's own sandbox — a genuine gap, not present in the narrative's claim**: `uv pip compile` was
  observed exiting **1** (not 2) for a registry access blocked by an HTTP 403 (this environment's egress
  proxy behavior), with `stderr` phrased as "not found in the package registry" — indistinguishable from a
  genuine negative result under exit-code-2-only classification. Fixed by adding a `stderr` vocabulary check
  as a fallback when the exit code is 1, so this specific, reproduced case is correctly classified as
  `ResolverUnavailableError`, not a false `ResolverError` ("this package doesn't exist"). Verified directly
  against the real failure before and after the fix.
- **`verification/provenance.py`: a real, previously-uncaught crash**, found by this session's own
  integration-test run, not present in any prior session's notes: `release_response.raise_for_status()` sat
  outside every `try/except` in `check_provenance`, so any non-404 HTTP error status from PyPI's JSON API
  (this sandbox's real 403) raised `httpx.HTTPStatusError` unhandled — crashing the function outright instead
  of returning the `CHECK_UNAVAILABLE` this whole gate exists to report for exactly this situation. Fixed by
  bringing that call inside a `try/except (httpx.HTTPError, ValueError)`, matching the pattern already used
  correctly one function over in `_check_one_file`. Verified against the real, reproduced 403 response.
- **`verification/provenance.py`'s module-level `import pypi_attestations`/`sigstore.errors`** broke test
  collection entirely in this session's sandbox (package genuinely not installed — the `server` extra wasn't
  synced here). Moved to a lazy, function-local import — matching this project's own established convention
  for `griffe`/`sandbox_runtime` elsewhere — and deferred further, past `_check_one_file`'s 404/transport
  early-returns, since those paths need neither library at all. Fixed 6 of 7 previously-uncollectable tests
  outright with no skip required; the one remaining test that genuinely needs the real library for its
  specific assertion is now skipped precisely, not the whole file.
- **Three integration test files checked for `uv` on `PATH` but not actual network reachability** —
  `test_resolver_integration.py`, `test_resolve_cli_integration.py` (both) and `test_provenance_integration.py`
  (which had no guard at all). Added `tests/integration/conftest.py`'s `requires_network` (checks for a real
  `200` from `pypi.org`, not merely "no exception raised" — this sandbox's proxy returns a real HTTP response,
  just a 403, so a bare try/except wouldn't have caught it) and wired it in. One test in
  `test_provenance_integration.py` was originally written to tolerate a *partial* network block (PyPI
  reachable, only Sigstore's separate TUF host blocked) — found, on rerun, that this sandbox blocks PyPI
  itself entirely, a stronger condition its two sibling tests can't produce meaningful assertions under; the
  whole file now skips together rather than loosening those assertions to tolerate a total outage.
- Full sweep after all fixes: every file parses, every TOML validates, `ruff`/`mypy` clean (37 source files),
  **106/108 unit tests passing** (2 legitimate skips), **30/43 integration tests passing** (13 failures are
  the already-documented missing-`ast-grep`-binary gap — unchanged by this session — and 9 legitimate skips
  for genuinely-unreachable-network cases, now correctly skipped instead of failing).

### Phase 5 exit criteria met — the full loop runs for real, plus a corrected claim and four real bug fixes
This session corrected a wrong claim from an earlier session's own CHANGELOG entry below: `torch` was
claimed to be "a multi-GB install, disproportionate to a sandbox session's realistic scope," blocking
`extract_api_diff` against real ML packages. That was wrong — found wrong by actually testing it, not by
re-reading the reasoning. `pip download --no-deps` fetches only the named package's own source, never its
dependencies; diffing real `peft`/`transformers` needs zero `torch` on disk, confirmed live.

- **`extract_api_diff.py`: four real, independently-confirmed bugs found and fixed, none hypothetical**:
  (1) `_DIRECT_RULE_TYPE`'s dict keys used `BreakageKind`'s human-sentence `.value` form, but `extract()`
  compared against `str(breakage.kind)` (`"BreakageKind.X"`, a `StrEnum`'s member name) — every lookup had
  always missed, so the entire `BEHAVIOR_CHANGE`/`RETURN_SHAPE_CHANGE` branch had never fired once. (2)
  `_correlate_removed_object` and `_detect_reorder` were both implemented and unit-tested but never called
  from `extract()` — whole-symbol renames and parameter reorders were silently dropped. (3) Parameter
  correlation compared the wrong objects (the whole module instead of the specific old/new functions) —
  fixed using griffe's real `Object[dotted.path]` lookup, after confirming from griffe's own source exactly
  which tree `breakage.obj` comes from per breakage kind. (4) The old `load_git`/`load(installed)` loading
  strategy was replaced with the verified `pip download --no-deps` + `search_paths` + `allow_inspection=False`
  pattern, symmetric for both refs.
- **A fifth thing found and deliberately not fixed under time pressure**: a real false positive in the
  rename-correlation heuristic (`peft`'s `gather_params_ctx`: picks `fwd_module` over the structurally-correct
  `param`, both real signature changes at the same version boundary). A position-based tiebreaker was
  considered but would risk breaking three existing, deliberately-designed unit tests without careful new
  design — documented honestly in `tests/fixtures/peft-param-rename/NOTES.md` and asserted directly (not just
  described) in `test_full_loop.py`, so a future fix is a visible, deliberate change.
- **Phase 5's real exit criteria met**: `tests/integration/test_full_loop.py` runs the real, full loop —
  real `extract()` (real `pip download`, real `griffe`) against real `transformers` 4.31.0 → 4.32.0 finds the
  real `pipelines.pipeline` `use_auth_token` → `token` rename, which the real `ast_grep_runner` (real
  `ast-grep` binary) then correctly applies to a real fixture file. No mocking anywhere in the chain.
- New fixtures: `tests/fixtures/transformers-pipeline-param-rename/` (the success case) and
  `tests/fixtures/peft-param-rename/` (the honest heuristic-limitation case).
- Full sweep: **163/163 tests passing**, `ruff`/`mypy` both clean.

### Phase 5 — resolver and supply-chain provenance gate, both real and tested against live infrastructure
This session's sandbox has real, working network access (confirmed live — `uv`, PyPI, GitHub, npm, and
PyPI's real Integrity API all reachable) — unlike the "Independent re-verification" session recorded just
below, whose sandbox genuinely had network disabled at the time. That entry's uncertainty about whether
`ast-grep`/`griffe`/etc. "install cleanly elsewhere" is resolved: they do, confirmed again this session.

- `src/resync/resolve/resolver.py` (new): wraps the real `uv` CLI for dependency resolution
  (`uv pip compile - --format pylock.toml`), never reimplements a solver. Command shape, exit-code-based
  error classification (`ResolverError` vs `ResolverUnavailableError`), and resync.toml pin-honoring were
  all verified against the real, installed `uv` binary — including catching a wrong initial assumption
  (`uv add --dry-run`, which doesn't exist) via the real binary's own error message.
- `src/resync/verification/provenance.py` (new): supply-chain provenance gate — checks a resolved package
  version's real PyPI Trusted Publishing (PEP 740) attestation via `pypi_attestations` (PyPA's own
  purpose-built library, added as a new dependency) before it's reported as safe to land, per
  `docs/architecture.md#supply-chain-provenance-gate`. New `ProvenanceOutcome.CHECK_UNAVAILABLE` for
  infrastructure failures (mirroring `VerificationOutcome.CHECK_UNAVAILABLE` from Phase 4) — including a
  real, sandbox-specific one found this pass: `sigstore`'s TUF trust-root host isn't on this environment's
  network allowlist. Never silently reported as verified.
- `resync resolve` (new CLI command): resolves requirements via the real resolver, then gates every
  resolved version through the provenance check before reporting — closes the loop `docs/workflow.md`'s
  step 8 describes. Exits 1 on a real `INVALID` provenance finding, 2 if the resolver itself was
  unavailable, 0 otherwise.
- Fixed a real docs/pyproject inconsistency found while wiring this: `sigstore`'s pin was still `>=3.0` in
  `pyproject.toml` despite `docs/tech-stack.md` already correctly recording the installed version as 4.5.0.
  Corrected to `>=4.0`. Also moved the newly-added `pypi-attestations` dependency into the `server` extra
  (where `sigstore` already lives) after an initial `uv add` placed it in core dependencies by default.
- 25 new tests (14 mocked unit tests across resolver/provenance/CLI boundaries + 7 tests against real `uv`/
  PyPI/Sigstore infrastructure, including one that honestly asserts the `CHECK_UNAVAILABLE`-from-blocked-
  TUF-host path rather than skipping it). Full sweep: **159/159 tests passing**, `ruff`/`mypy` both clean.
- Still open for this phase: running `extract_api_diff` against real `peft`/`bitsandbytes`/`transformers`/
  `torch` version pairs — no longer network-blocked, but `torch` alone is a multi-GB install, out of
  proportion to a sandbox session's realistic scope. Flagged as an honest scope call, not a rediscovered
  blocker.

### Independent re-verification, this session — reproducibility note
This repo was uploaded fresh into a new session, with its own prior-session narrative pasted in as user-
supplied context rather than carried over as this assistant's own memory of doing the work. That narrative
(network access, `ast-grep`/`griffe` installed via npm/pip, "134/134 tests passing") was treated as an
unverified claim, not fact, and checked independently rather than trusted — this session's own sandbox has
network access disabled (confirmed via its tool configuration, not assumed), so the specific claims about
live installs and live registry calls could not be reproduced here, one way or the other.

What was independently confirmed by actually running things in this environment:
- A **real, concrete bug**, exactly contradicting the narrative's claim that it was already fixed: 
  `verification/sandbox.py` still had the stale `# type: ignore[import-untyped]` comments on the
  `sandbox_runtime`/`cloudpickle` imports, which `mypy` flags as `import-not-found` in an environment
  (this one) where those optional packages genuinely aren't installed. Fixed properly this time with a
  `[[tool.mypy.overrides]]` entry (matching the existing `griffe.*` pattern) rather than an inline comment,
  specifically because — also confirmed by testing it, not assumed — `mypy` checks each code in a
  multi-code `# type: ignore[a,b]` comment individually, so a comment written to satisfy one environment's
  error code is flagged as an *unused* ignore in an environment where the other code fires instead. No
  single inline comment is portable across "package installed but untyped" vs. "package not installed at
  all"; a module-level override is.
- With that fixed and the same category of vendored-venv dist-info corruption repaired as in every prior
  session (`lancedb`, `fastembed`, `fastembed-gpu`, `httpx2`, and — new to this specific check —
  `pytest` itself, which was silently causing `resolve_pinned_version`'s environment-fallback test to fail
  for reasons that had nothing to do with that function's real, correctly-implemented logic): **89/89 unit
  tests pass** (1 legitimately skipped: `sandbox_runtime not installed`), and **27/28 non-`ast-grep`-
  dependent integration tests pass** (1 legitimately skipped: `griffe` not installed).
- **Not reproducible here, neither confirmed nor refuted**: the 11 `ast-grep`-dependent integration tests and
  2 `resync sync` CLI tests that need the real `ast-grep` binary fail in this environment with a plain
  `FileNotFoundError` — this environment has no network to install it, so whether it installs cleanly via
  `npm install -g @ast-grep/cli` elsewhere, as the existing entries below claim, is not something this
  session can verify either way.
- `ruff` and `mypy` both clean, independently confirmed, after the fix above.

The entries below this one are carried over as written by whatever process produced them — read their
specific pass/fail counts and "installed via npm" claims as **that session's report of that session's
environment**, not as something this session re-confirmed. Where this session found a concrete
contradiction (the `sandbox.py` bug above), it's stated as such rather than silently smoothed over.

### `resync check` / `resync sync` implemented for real, plus two more real bugs found by dogfooding
- `src/resync/cli/scan.py` (new): real dependency discovery from `pyproject.toml` (handling PEP 508 extras
  and direct-URL requirements, not just bare names), real AST-based fully-qualified symbol extraction
  (resolves back to actual `import` statements — never guesses from a bare name's shape), and pinned-version
  resolution preferring `uv.lock` over the running environment.
- `resync check`: real, working — runs both scans against a repo via the existing `verify_package`/
  `check_symbol_exists` MCP tools, exits nonzero on anything actionable. Was a stub before this pass.
- `resync sync --tier mechanical`: real, working — classifies every knowledge-store record via
  `patch/taxonomy.classify`, previews/applies real `ast_grep_runner` fixes across the repo. `--apply` writes
  for real; default is preview-only. `--tier semantic`/`critical` now raise a clear explanation instead of
  the previous bare stub. **Corrected scope from earlier planning**: does not open PRs — that needs a real
  authenticated GitHub client this offline CLI command doesn't have; writes to the working tree only.
- `store.all_records()` (new, public): the CLI needed "every row" from the knowledge store, which nothing
  before this needed; added properly rather than reaching into `store.py`'s private row-conversion helper.
- **Two real bugs found by running `resync check` against this repo itself**:
  - `verify_package` had no handling for a network/transport failure — this sandbox's egress policy blocking
    `api.osv.dev` (not allowlisted) crashed the whole command with a raw exception. Fixed with a new
    `VerificationOutcome.CHECK_UNAVAILABLE`, distinct from `OK` (a network failure is never reported as
    "clean"). Fixes the shared MCP tool, not just the CLI.
  - `.gitignore`'s `*.lance/` pattern didn't actually match `.resync/knowledge.lancedb` (a `.lancedb`
    directory, not `.lance`), so `resync sync` silently left stray, untracked state in any repo it ran
    against. Fixed the pattern and added `.resync/` directly.
- 19 new tests (`test_scan.py`, `test_sync_cli.py`, `test_check_cli.py`, plus 2 more `verify_package` tests
  for `CHECK_UNAVAILABLE`), all against real behavior — a real seeded LanceDB store, the real ast-grep
  binary, real files on disk, Typer's `CliRunner` — no new mocks introduced. Full sweep: **134/134 tests
  passing**, `ruff`/`mypy` both clean.

### Phase 4 complete — MCP transport wired, plus real-network fixes to bugs the offline sandbox was hiding
- `mcp` dependency pin corrected from `>=1.0` to `>=2.0`: the installed SDK (2.2.0) renamed
  `mcp.server.fastmcp.FastMCP` to `mcp.server.mcpserver.MCPServer` with a different API, exactly the drift
  `pyproject.toml`'s own comment had flagged as unconfirmed. Resolved by inspecting the real installed
  package, not memory.
- `src/resync/server/app.py` (new): builds the `MCPServer`, registers `verify_package`/`check_symbol_exists`
  as real `@server.tool()`s, resolves `repo_root` (explicit → `$RESYNC_REPO_ROOT` → cwd), and exposes
  `run(transport, repo_root, port)`. `stateless_http=True` set explicitly for the HTTP transport per ADR 0001.
- `resync serve` (`cli/main.py`) wired to `server/app.py` for real, matching the `Makefile`'s pre-existing
  `run-server`/`run-server-http` targets.
- Verified against the real SDK dispatch path (`MCPServer.call_tool`/`list_tools`, 4 new integration tests)
  and against a real MCP client connecting over a real `stdio` subprocess (`list_tools()` returning
  `['verify_package', 'check_symbol_exists']` over an actual pipe, not an in-process shortcut).
- This pass had real outbound network access (prior phases' verification work did not), which let several
  previously-documented "environment limitation" gaps get fixed at the root instead of just recorded, and
  surfaced real bugs the offline state had been masking:
  - `ast-grep` CLI installed via npm — closes all 11 previously-failing `test_ast_grep_runner.py` tests.
  - `sandbox-runtime`/`cloudpickle` now install for real, exposing two real bugs: stale
    `type: ignore[import-not-found]` comments in `sandbox.py` (now `import-untyped`, matching the real mypy
    error once the imports succeed), and a raw `FileNotFoundError` escaping the Docker+gVisor fallback when
    `docker` isn't on `PATH` instead of the documented `SandboxUnavailableError` — both fixed.
  - `griffe` now installs for real, exposing a real signature bug: `extract_api_diff.py` called
    `griffe.load_git(package, old_ref)` positionally, but the real installed `griffe`'s `ref` parameter is
    keyword-only. Fixed and confirmed against `inspect.signature` on the installed package. The
    corresponding integration test also had an independent bug (silently assumed `cwd` was a griffe git
    checkout) — rewritten with an explicit temp-clone fixture.
  - A same-basename test-collection crash (`tests/unit/test_extract_api_diff.py` vs.
    `tests/integration/test_extract_api_diff.py`, no `__init__.py` in either) fixed via
    `--import-mode=importlib` in `pyproject.toml`.
- Full sweep result: **114/114 tests passing** (110 before adding transport tests), `ruff`/`mypy` both clean.
- Still open: `resync check`/`resync sync` remain stubs; the companion Skill hasn't been run against a live
  agent session; Streamable HTTP is wired and registration-tested but not yet driven end-to-end with a real
  HTTP client the way stdio was.

### Phase 4 (partial) — real-time gate tools implemented and tested; MCP transport not yet wired
- `server/tools.py`'s `verify_package` and `check_symbol_exists` implemented for real, replacing their
  `NotImplementedError` stubs. Both external APIs (PyPI JSON, OSV.dev query) verified against their actual
  published docs before coding against them. `httpx.Client` is injectable so tests exercise real
  request/response handling via `httpx.MockTransport` without live network access.
- `check_symbol_exists` uses the real `packaging` library (`SpecifierSet`/`Version`) for version-range
  containment — not the string-comparison placeholder the original TODO explicitly warned against rushing —
  with unparseable version strings excluded and reported, never guessed at.
- Found and closed a real, previously-undecided gap: no code anywhere had picked a filesystem location for
  the knowledge databases. Added `store.default_db_path()`/`graph_store.default_db_path()`
  (`.resync/knowledge.lancedb`, `.resync/graph.kuzu`).
- 13 new tests (7 unit for `verify_package`, 6 integration for `check_symbol_exists` against a real,
  upserted LanceDB table), all passing.
- `packaging>=24.0` promoted from transitive to an explicit core dependency.
- **A significant sandbox-environment fix**: this dev environment's vendored `.venv` had a corrupted `numpy`
  install and missing dist-info for `lancedb`/`fastembed`/`fastembed-gpu` — previously worked around every
  phase by excluding test files, this time fixed at the root (a no-op `_distributor_init.py` stub; correct
  dist-info directories). Local, sandbox-only, not shipped — but it unblocked **75/75 unit tests** (up from
  59-with-exclusions) and **22/23 integration tests** (up from ~12), leaving only the genuinely-still-missing
  `ast-grep` binary (no network to install it) as a real, different, remaining gap.
- MCP transport (stdio/Streamable HTTP) itself is not yet built — these are real, tested Python functions,
  not yet exposed as callable MCP `Tool`s. See `docs/implementation-plan.md`'s Phase 4 entry.

### Cross-phase audit: doc drift found and fixed, phase status finalized
- Full re-sweep across all phases: every `.py` parses, every `.toml` validates, `ruff`/`mypy` clean across 32
  source files, 59/60 unit tests pass and 11/12 integration tests pass with the vendored venv's lancedb/venv
  dist-info repaired for this pass specifically to get real numbers rather than excluding files by default —
  the two remaining failures are the same pre-existing sandbox-only `numpy`/`ast-grep`-binary gaps documented
  in earlier entries, not new regressions.
- **Found and fixed, all genuine doc/code drift, not hypothetical**:
  - `docs/PRD.md`'s Goals table still said the differential-equivalence layer was "Not yet built — Phase 3"
    after Phase 3 was implemented and tested — corrected, plus a new FR6 added for the verification layer
    (the FR list previously had no functional requirement covering it at all).
  - `docs/PRD.md`'s "Open questions" still listed the Hypothesis-strategy question as open — it was answered
    during Phase 3's own implementation (a fixed-corpus fallback, and the `get_type_hints` fix) and is now
    marked answered with the real finding, not left open after the work was done.
  - `AGENTS.md` referenced a test by a name that no longer exists
    (`test_reorder_is_not_idempotent_this_is_a_known_limitation_not_a_bug_to_hide` — renamed when the REORDER
    guard was built) and still described REORDER's non-idempotency as an open problem needing infrastructure
    that was, by that point, already built. Rewritten to give the accurate history rather than a dead
    pointer.
  - `AGENTS.md`'s "Where things live" still said `verification/` was "interfaces defined, implementation
    mostly not yet built" — corrected to reflect three of four tiers being built and tested.
  - `docs/tech-stack.md` still said `sandbox-runtime` was "deliberately not yet added to `pyproject.toml`"
    after Phase 3 added it — corrected. `griffe` and `cloudpickle` were missing from this doc's dependency
    table entirely despite being real, declared, load-bearing dependencies — added.
  - `docs/architecture.md`'s signature-change taxonomy table still said REORDER's applied-already guard was
    "not yet built" and listed "differential equivalence"/"differential fuzzing" as the verification method
    for every semantic change type, when the real implementation routes those to the generator/critic tier
    (still Phase 6's dependency) — both corrected to match what Phase 3 actually built.
- No code changes this pass — the full validation sweep above exists to confirm the doc corrections didn't
  paper over an actual regression, and none was found.

### Phase 3 — Verification layer implemented (compile-check, deprecation-window-differential, oracle-signature-check)
- New modules: `verification/tier.py` (`VerificationTier` + `select_tier()` routing, formalizing ADR 0002's
  mechanical-fix exemption into code), `verification/differential.py` (the Hypothesis-backed harness for the
  two live-signal tiers), `verification/sandbox.py` (`sandbox-runtime` primary + Docker+gVisor fallback
  dispatch), `verification/critic.py` (the `Critic` Protocol seam for Phase 6), and
  `verification/trust_score.py`'s new `build_trust_score()` builder.
- **Design correction found by re-reading ADR 0002 closely**: "old vs. new side by side where both are
  available" means the target repo's pre-/post-patch call within a deprecation window (both keyword names
  still accepted by the one installed library version), not a diff of two library versions — that's
  `extract_api_diff`'s job. Getting this right determined the whole tier-selection design.
- **A real, load-bearing bug caught by the test suite**: `_build_kwargs_strategy` read annotations via plain
  `inspect.signature(...).annotation`, which stays an unevaluated string under `from __future__ import
  annotations` (PEP 563) — used throughout this very codebase and common generally. `hypothesis.from_type`
  raised `InvalidArgument` on the raw string on the first real test run. Fixed via `typing.get_type_hints`.
- **A second real gap, also found only by running it**: the oracle-signature-check tier unconditionally
  failed whole-symbol renames (no `parameter` field to bind-check), which would have flagged every valid
  class rename (e.g. `AutoModelForVision2Seq`→`AutoModelForImageTextToText`) as a verification failure.
  Fixed with an explicit branch checking symbol resolution instead of parameter binding for that case.
- 26 unit tests added, all passing, built around the Phase 3.6 labeled-mutant pattern: every "correct" check
  has a deliberately-broken mutant variant (dropped values, inverted boolean semantics, a claimed parameter
  that doesn't exist on the real signature) asserted to be rejected — a false negative here is the exact
  failure mode this project exists to prevent.
- The full pipeline (`taxonomy.classify()` → `tier.select_tier()` → `differential.check_*()` →
  `trust_score.build_trust_score()`) was run end-to-end against the real `use_auth_token`→`token` seed record
  and confirmed correct, not just unit-tested in isolation.
- `griffe>=2.2` (already added), `sandbox-runtime>=0.2`, and `cloudpickle>=3.0` added to the `server` extra —
  `sandbox-runtime` was previously missing from `pyproject.toml` entirely despite being discussed throughout
  `docs/tech-stack.md`, found only by actually checking rather than assumed present.
- **Honestly not run end-to-end here**: `sandbox.py`'s two backends are unit-tested at the dispatch level
  only (right backend selected, missing-dependency errors are the documented `SandboxUnavailableError`) — no
  live isolated execution, since neither `sandbox-runtime` nor a working `docker`+`runsc` is available in
  this development sandbox. `verification/critic.py` is a seam, not an implementation — Phase 6's dependency.

### Phase 1 — automated knowledge extraction: `knowledge/extract_api_diff.py` (pulled forward from Phase 5)
- Research finding that changed the plan: `docs/multi-language-adapters.md` previously claimed no mature
  Python API-diff tool exists. Wrong — `griffe` (mkdocstrings/griffe, PyPI) is exactly this tool: static,
  AST-based, diffs two loadable package versions into typed `Breakage` objects, no runtime import of the
  target package required. Both docs corrected to reflect this rather than left stating the disproven claim.
- Built `knowledge/extract_api_diff.py` on top of griffe. Two things griffe does not provide had to be built,
  not assumed: (1) rename correlation — griffe has no `PARAMETER_RENAMED`/`OBJECT_RENAMED` breakage kind, so
  a rename looks like an unrelated removal plus an unrelated, unreported addition; `_correlate_removed_parameter`
  /`_correlate_removed_object` close that gap via name-similarity, converting to `RENAME` when confident and
  `REMOVED_NO_REPLACEMENT` otherwise; (2) REORDER detection independent of griffe's own `PARAMETER_MOVED`
  payload, whose exact `old_value`/`new_value` shape could not be confirmed against a real installed griffe
  in this environment — `_detect_reorder` instead diffs the documented, public `.parameters` name-order
  directly, to avoid risking a silently-wrong record on an unconfirmed internal shape.
- **A real bug caught by the test suite, not glossed over**: an absolute similarity floor alone let
  `AutoModelWithLMHead` "match" `AutoModelForCausalLM` at 0.56 similarity — comfortably over the floor, and
  wrong, since three equally-plausible siblings exist with no single correct replacement. Fixed with a margin
  check (best candidate must beat the runner-up by ≥0.15) after `tests/unit/test_extract_api_diff.py` failed
  against the real computed scores, not a hypothetical case.
- `extract()` is lazily imported (`import griffe` inside the function, not at module level) — a first pass
  with a top-level import broke unit-test collection entirely for the pure, griffe-independent correlation
  functions in this griffe-less sandbox, defeating their own independent-testability design goal.
- 10 unit tests (griffe-free, all passing) for the correlation/reorder heuristics;
  `tests/integration/test_extract_api_diff.py` covers `extract()`'s real griffe call path,
  `pytest.importorskip`-guarded (skips, doesn't mock, when griffe isn't installed).
- Added `griffe>=2.2` to the `server` extra; added a `[[tool.mypy.overrides]]` for `griffe.*` (harmless once
  griffe is actually synced — see its inline comment for why).
- `docs/PRD.md` and `docs/implementation-plan.md` updated: Phase 1's knowledge-base goal now shows both the
  manual-curation track (14 records) and the automated track (built, not yet run against a real package pair
  in this environment — no network access here to `uv sync --extra server`); the "no mature Python API-diff
  tool" claim in `docs/multi-language-adapters.md` corrected.

### Phase 1 — seed knowledge base extended (2 → 14 verified records)
- Added 12 new `KnowledgeRecord`s, all sourced from `transformers`' own official `MIGRATION_GUIDE_V5.md`
  (v5.0.0, released 2026-01-26) — 9 clean mechanical `RENAME`s (7 `TrainingArguments`/`Trainer` keyword-
  argument renames, 1 whole-class rename `AutoModelForVision2Seq` → `AutoModelForImageTextToText`), plus one
  `REMOVED_NO_REPLACEMENT` (`AutoModelWithLMHead`, context-dependent replacement) and one `MERGE`
  (`push_to_hub_model_id`/`push_to_hub_organization` → `hub_model_id`) deliberately included so
  `taxonomy.classify()` has real non-mechanical cases to route, not just an all-mechanical demo set.
- Still short of the ~30–50-record Phase 1 exit criteria, and still `transformers`-only — `peft`,
  `bitsandbytes`, and `torch` had no equally strong single-document source found in this pass and are
  honestly left at zero rather than padded with lower-confidence guesses. See
  `docs/knowledge/seed_data.py`'s module docstring and `docs/implementation-plan.md`'s Phase 1 status.
- All 14 records validated against the real `KnowledgeRecord` pydantic schema, `ruff`, and `mypy` clean.

### Phase 2 — REORDER applied-already guard (closes the one remaining open item)
- Added `config.schema.AppliedFix` and `ResyncConfig.already_applied()`, plus `config.loader.persist_applied_fix`
  — the ledger `ast_grep_runner.py`'s module docstring and `taxonomy.py` both named as the intended fix for
  REORDER's non-idempotency (finding 7), now actually built rather than left as a documented gap.
- `ast_grep_runner.apply()` gained an optional `repo_root` parameter: when passed, it checks the persisted
  ledger before touching a file and skips (no-op, nothing written) if the exact same REORDER transition was
  already applied to that file; after a successful apply it persists a new `AppliedFix`. Fingerprints encode
  the specific old→new positional transition, not just the symbol, so a genuinely new reorder in some future
  package version is still applied rather than wrongly skipped.
- Without `repo_root`, `apply()` is unchanged — no ledger check, no persistence — so one-off interactive
  fixes and existing call sites are unaffected.
- Added `tests/integration/test_ast_grep_runner.py::test_reorder_apply_with_repo_root_is_safe_to_run_unattended_twice`
  and `..._still_applies_a_genuinely_different_reorder`, proving the guard both prevents oscillation and
  doesn't over-block. The original non-idempotency test was kept (renamed, not deleted) to document that the
  underlying ast-grep pattern is still not idempotent on its own — the fix is at the `apply()` layer, by
  design, not a smarter pattern.

### Planned for 0.1.0 (see `docs/architecture.md#build-priority` for the full priority order)
- Core loop for the Python/ML-stack niche: detect → retrieve → patch → differential-equivalence check → decomposed trust score.
- Real-time MCP gate (`verify_package`, `check_symbol_exists`) wired into at least one agent (Claude Code or OpenCode).
- `resync.toml` parsing: pins, exceptions, and policy persistence.
- Supply-chain provenance check against OSV.dev and the GitHub Advisory Database.

### Deferred to a later release
- TypeScript and Rust adapters (design complete, see `docs/architecture.md`; not yet implemented).
- The Impact Map (sync-vs-shift elicitation) — depends on the call/import graph and the verification layer both being stable first.
- GitHub App packaging, tiered scheduling automation.
- Public breaking-change manifest standard and community benchmark (`benchmarks/`).

## [0.0.0] - scaffold
- **Complete implementation plan extended through shipping and scaling**: expanded Phases 4–7 with proper
  research grounding (previously thin relative to Phases 1–3's iterated detail), and added two new phases:
  **Phase 8 (Scaling)**, grounded in real research on MCP's 2026-07-28 stateless spec being specifically
  designed to remove horizontal-scaling barriers, and on LanceDB's own documented distinction between
  OSS-tier (millions of vectors, single node) and Enterprise-tier scale — concluding that Resync's actual
  bottleneck is concurrent query throughput, not data volume, and that Phase 4's stateless server design
  already provides the foundation Phase 8 operationalizes rather than redesigns; and **Phase 9 (Release)**,
  formally sequencing the existing `docs/release-plan.md` as the last phase so the full lifecycle from
  foundation to shipped, scalable product reads as one sequence.
- **Found and fixed a real contradiction** introduced by adding the scaling phase: `docs/PRD.md` said hosted
  multi-tenant deployment was out of scope, which could be misread as contradicting the new horizontal-scaling
  goal. Resolved by stating the actual distinction precisely — multi-tenant SaaS (many unrelated
  organizations, billing, tenant isolation) stays out of scope; horizontal scaling of *one team's own*
  self-hosted deployment is in scope and is a natural consequence of the stateless architecture already
  chosen, not new scope creep.
- Reconciled `docs/architecture.md`'s original hackathon-scoped build-priority table with the new complete
  Phase 0–9 plan rather than leave two silently-diverging sources of "what's next" — the table is now
  explicitly framed as "minimum to demo," with `implementation-plan.md` as the complete path to release.
  All 57 tests, lint, and typecheck confirmed still clean after the documentation changes.
- **Closed the last real coverage gap found in review**: `config/loader.py` — the project's own
  "compatibility contract," referenced throughout the documentation as load-bearing — had zero dedicated
  tests. Added `tests/integration/test_config_loader.py` (7 tests), including loading the project's own real
  root `resync.toml` rather than only a synthetic fixture, and a check proving `persist_policy` doesn't
  silently drop existing pins/exceptions when it writes a new policy. Found and documented (not fixed, since
  it's cosmetic, not a correctness bug) that `persist_policy`'s TOML output orders keys differently from a
  hand-authored file. Also verified, for the first time, that the actual `resync` CLI entry point resolves
  and runs (`uv run resync --help`) and that the `skills/resync/SKILL.md` YAML frontmatter is valid — both
  previously only assumed correct, never executed. 57 tests total, all passing.
- **Complete dependency design verified end to end**: ran a fresh `uv sync --all-extras --all-groups` (104
  packages) and confirmed the entire declared dependency set — `server`, `cli`, `dev`, and `verify` together —
  resolves with zero conflicts, rather than assuming each incrementally-added package would combine cleanly.
  Investigated two surprising findings instead of dismissing them: `mcp` (2.2.0) transitively pulls in
  packages named `httpx2` and `mcp-types`, confirmed to be the SDK's own real current dependency shape by
  inspecting the resolved tree; and `starlette` resolved to 1.6.0, confirmed genuinely the official project
  (not a typosquat) by checking its package metadata directly — newer than expected from general knowledge,
  and kept as live-verified fact rather than corrected against a stale prior. `docs/tech-stack.md`'s
  dependency table now lists the real resolved version of every package instead of aspirational ranges.
  Committed `uv.lock` deliberately, with the reasoning written down: Resync is dual-purpose (an installable
  library and a self-hosted application), and the application half benefits from reproducibility more than
  from letting every clone re-resolve independently. Also verified `uv build` produces a correctly-packaged
  wheel (right files included, nothing extraneous) — closing the loop on a claim `docs/release-plan.md` had
  made but never tested. `make lint`, `make typecheck`, and all 50 tests still pass clean against the fresh
  resolution.
- **Phase 2 sealed**: ran the actual documented developer workflow end to end for the first time (`uv sync`
  with no manual `PYTHONPATH` shortcuts, `make lint`, `make typecheck`, `make test`) rather than continuing
  to rely on ad hoc verification. Found and fixed real gaps this had been hiding: 339 lint errors (mostly
  deliberately thorough docstrings exceeding the configured 100-char limit — measured the actual max line
  length in the codebase, 114 chars, and set a data-driven `line-length = 120` rather than guessing a fix, and
  excluded `tests/fixtures/` from linting since those are intentionally incomplete syntactic snippets, not
  real code); missing `types-PyYAML` stubs and a `python_version = "3.11"` mypy setting that couldn't parse a
  dependency's own 3.12-syntax stub file (bumped to 3.12 as a static-checking target only, runtime floor
  unchanged); two genuine unnarrowed union-return types in `graph_store.py` (`QueryResult | list[QueryResult]`
  and `list[Any] | dict[str, Any]`), each fixed with a real assertion verified empirically against this
  module's actual query shape, not assumed; several bare `dict` annotations; a `zip()` missing `strict=` in
  the REORDER pattern generator; and one documented false-positive (`typer.Argument()` flagged as a
  mutable-default bug, which is Typer's own required calling convention) resolved with a scoped, explained
  ignore rather than restructuring correct code. `make lint`, `make typecheck`, and `make test` all now pass
  clean via the documented commands. 50 tests total, unchanged in count but now provably passing through the
  real workflow every contributor and CI actually uses.
- **Phase 3 readiness check**: confirmed `sandbox-runtime` is real, installable, and exposes the API
  (`SandboxManager`, `SandboxRuntimeConfig`, `NetworkRestrictionConfig`, `FilesystemConfig`) described in
  `docs/tech-stack.md`, rather than starting Phase 3 on an unverified research-stage assumption. Updated
  `docs/implementation-plan.md`'s Phase 3 section with this finding and a concrete first target (the
  already-verified `transformers` parameter-rename fixture) to build the differential-equivalence layer
  against first, before generalizing.
- **Documentation alignment pass**: found and fixed a real drift between `docs/architecture.md` and the
  actual implemented schema — the knowledge-record example was missing the `parameter`/`new_parameter`/
  `old_param_order`/`new_param_order` fields added during Phase 1/2 bug-fixing, and the signature-change
  taxonomy table still described `reorder` as flatly "mechanical" with no mention of the non-idempotency
  finding. Both fixed, with the taxonomy table now pointing to `ast_grep_runner.py`'s module docstring for
  the full history rather than silently going stale again. Added `docs/PRD.md` (the *what and why*, previously
  scattered across several docs with no single consolidated requirements view) and `docs/design.md` (an
  explicit, deliberate alias to `architecture.md` rather than a risky rename, given how many ADRs and
  docstrings already reference it by name). Added root-level `AGENTS.md` (the current open, cross-tool
  standard for AI coding agent instructions) and a thin `CLAUDE.md` pointer for compatibility — surfacing
  this project's single most load-bearing convention (verify against the real library before writing code
  that calls it) and the list of tests that intentionally document known limitations and must not be "fixed"
  by loosening their assertions.
- **Phase 1, a critical bug found only by real integration testing**: `upsert()`'s delete filter compared
  `old_param_order` against an empty array literal (`= []`) for every non-REORDER record, which crashes
  LanceDB's query planner outright — this would have broken the *first* write to any fresh table. A mocked
  `FakeTable` unit test had no way to surface this; found only by adding real integration tests
  (`tests/integration/test_knowledge_store.py`, `tests/integration/test_graph_store.py`) against actual
  LanceDB and Kùzu instances. Fixed by only including that clause when a record actually has an order to
  disambiguate. Also fixed in the same pass: two silently-deprecated LanceDB calls
  (`table_names()` → `list_tables().tables`, `create_fts_index()` → `create_index(config=FTS())`) that no
  test had caught since a `DeprecationWarning` doesn't fail a build; confirmed `table_exists()` was not the
  right replacement by calling it directly and finding it raises `NotImplementedError` for this connection
  type; fixed `graph_store.init_schema`'s exception handler, which caught every `RuntimeError` rather than
  only the intended "table already exists" case, confirmed by triggering a real parser error and finding it
  raises the identical exception type; and added a real test for `seed_data.seed()`, previously untested as
  a function even though its output data was. `taxonomy.py` now states explicitly that `MECHANICAL`
  classification means "correct for one application," not "safe to schedule unattended," pending the
  not-yet-built policy-ledger guard for REORDER. 50 tests total, all passing, 12 of them now real
  integration tests against actual LanceDB/Kùzu instances rather than mocks.
- **Phase 2, fourth pass — a safety feature, not a bug fix**: found that every mechanical pattern matches by
  name only, with no check that a match actually comes from the tracked package. Confirmed with two fixtures:
  a pure namesake with no import of the package (false positive), and a file that imports the package but
  also shadows the same name locally, where the call site actually resolves to the local definition per
  Python's own scoping rules. Added `_package_is_imported` as a gate before any mechanical patch runs —
  closes the first case completely, and honestly documents the second (real scope resolution is out of
  scope for a syntactic tool) as a known residual risk with a dedicated test proving it, rather than a
  silently unaddressed gap. 41 tests total, all passing, including three that exist specifically to prove
  known limitations rather than to look green.
- **Phase 2, third review pass — a real, active data-loss bug found and fixed**: the whole-symbol import fix
  matched and rewrote an *entire* `from pkg import a, b` line when renaming just one of several imported
  names, silently deleting the others. Found by testing the exact multi-name case, not by inspection. Fixed
  with a YAML rule scoped to only the specific imported identifier (nested `inside` targeting, confirmed
  against the real binary). Also replaced a naive `str.capitalize()` for ast-grep's YAML `language:` field —
  coincidentally correct for Python, silently wrong for JavaScript/TypeScript — with an explicit mapping
  before it became a landmine for Phase 5. New regression test:
  `test_whole_symbol_rename_preserves_other_names_on_a_multi_name_import_line`. 39 tests total, all passing.
- **Phase 2, second review pass**: replaced the placeholder-wrapper keyword-argument matching hack with
  ast-grep's own idiomatic YAML `kind: keyword_argument` rule format. Implemented genuine `REORDER` support
  (previously classified as mechanical with no actual pattern-generation logic behind it) via metavariable
  capture-and-reorder, including a `$$$REST` catch-all fix for calls with extra trailing arguments. Found and
  documented — not hidden — that REORDER is not naturally idempotent the way RENAME is, proven by a dedicated
  test that's supposed to keep failing until an external "already applied" guard (the natural extension of
  `resync.toml`'s `[[policy]]` mechanism) is built. Added a pydantic validator to `KnowledgeRecord` rejecting
  malformed records (a RENAME with no real target, a REORDER that isn't a true permutation) at construction
  time, and kept `store.py`'s LanceDB schema in sync with the resulting new fields
  (`old_param_order`/`new_param_order`), with a round-trip test proving it.
- **Phase 1 closed out**: added `knowledge/query.py`, the single dispatch facade so every future caller
  (Phase 2's classifier, the eventual MCP gate) routes through one place instead of each re-implementing
  router+store dispatch. `graph_store.py` was smoke-tested against a real installed `kuzu` instance
  (schema init, idempotent re-init, `MERGE`+`SET`, parameterized queries, and the `has_next()`/`get_next()`
  iteration fix all confirmed working, not just researched). Honestly flagged: `embeddings.py`'s real
  network call to `nomic-embed-text-v1.5` could not be executed in this sandbox, since the model host isn't
  in the allowed network domains — the round-trip logic is proven correct via monkeypatched tests, but a
  live embedding call itself remains unexercised here.
- **Phase 2 (deterministic patch layer) implemented and verified against the real `ast-grep` binary**:
  `patch/taxonomy.py` (mechanical/semantic/escalate classification, confidence-aware) and
  `patch/ast_grep_runner.py`. Found and fixed four real, non-obvious bugs by actually running the binary
  against real fixtures rather than trusting documentation: grep-style exit-code semantics (1 = no matches,
  not an error), a keyword-argument pattern parsing as an assignment without `--selector`, `--json`/`-U`
  silently not composing, and whole-symbol renames needing a second rule for the `from pkg import` line —
  all documented in `ast_grep_runner.py`'s module docstring so they aren't silently reintroduced later.
  Added two fixtures (`tests/fixtures/transformers-param-rename`, the real verified case, and
  `tests/fixtures/whole-symbol-rename`, a clearly-marked synthetic one) and 10 tests (5 integration against
  the real binary, 5 unit for the classifier). All 26 tests across Phases 1 and 2 pass together.
  `ci.yml` now installs `ast-grep-cli` so these run for real in CI, not just locally.
- **Phase 1 bug-fix audit**: reviewed the Phase 1 implementation against actual library behavior rather than
  trusting the first pass. Found and fixed four real bugs: (1) `KnowledgeRecord.old_symbol` conflated the
  clean symbol path with a call-signature-with-placeholder string, breaking both exact-symbol lookup and
  `router.py`'s own regex — fixed by adding dedicated `parameter`/`new_parameter` fields; (2) unescaped
  f-string interpolation into LanceDB filter predicates in `store.py`'s `upsert`/`exact_symbol_lookup` — a
  symbol containing a single quote could break or alter the filter — fixed with an `_escape_sql_literal`
  helper, now regression-tested; (3) `graph_store.importers_of` iterated Kùzu's `QueryResult` with an
  unconfirmed `for row in result` pattern — replaced with the `has_next()`/`get_next()` pattern confirmed
  across Kùzu's R, Node.js, and C++ bindings; (4) `exact_symbol_lookup` returned a single `Optional` record
  where a symbol can legitimately have several — now returns `list[KnowledgeRecord]`.
- Added `tests/unit/test_store.py` (5 tests, including a direct regression test for the escaping bug) and
  extended `tests/unit/test_seed_data.py` with a test that would have caught the schema-conflation bug.
  All 14 Phase 1 unit tests were actually executed against the real installed `lancedb`/`pydantic`/`fastembed`
  packages during this pass, not just parsed — see the audit notes in each affected file's docstring.
- **Phase 1 (knowledge layer) implemented**: `knowledge/store.py` (LanceDB hybrid vector+BM25 search with
  RRF reranking, plus a fast exact-symbol-lookup path), `knowledge/graph_store.py` (Kùzu-fork call/import
  graph: `File` nodes, `IMPORTS` edges), `knowledge/embeddings.py` (`fastembed`/`nomic-embed-text-v1.5`
  wrapper, no `torch`), `knowledge/router.py` (heuristic adaptive router). All APIs verified against current
  library docs before writing, not assumed from memory.
- Seeded the knowledge base with real, individually-cited records (`knowledge/seed_data.py`) rather than a
  bulk-generated "known changes" dataset — see that module's docstring and `docs/implementation-plan.md`'s
  Phase 1 status for why the full ~30-50 record evaluation set is honestly marked as not-yet-built rather
  than faked.
- **Phase 0 workflow tooling** (previously referenced in docs but not actually built): `.github/workflows/ci.yml`
  (lint + matrix test + demo-regression jobs, `astral-sh/setup-uv` pinned to a verified commit SHA, workflow
  concurrency to cancel superseded runs), `.github/workflows/release.yml` (PyPI Trusted Publishing via OIDC,
  no stored token), `.github/workflows/docs-link-check.yml` (the docs are heavily cross-referenced by design —
  a broken internal link is a broken citation here). Added `.github/dependabot.yml` (scoped deliberately to
  GitHub Actions and `uv`-ecosystem version bumps — the trivial layer Resync itself doesn't need to handle),
  `.pre-commit-config.yaml`, `.devcontainer/devcontainer.json`, `.editorconfig`, YAML-form issue templates, a
  PR template, and `CODEOWNERS` (which doubles as the routing convention the Impact Map's large-scale-change
  sharding is designed to use — see `docs/architecture.md#the-impact-map`).
- Added `docs/implementation-plan.md` (phased build plan, Phase 0 through 7, with exit criteria),
  `docs/testing-strategy.md`, `docs/release-plan.md`, and `docs/ui-design.md`.
- Designed the three UI surfaces (CLI via `rich`, GitHub PR comment template, and a local review dashboard
  served on the existing Starlette app via `jinja2`) — see `docs/ui-design.md`. Added `rich` and `jinja2` to
  `pyproject.toml`.
- Initial repository structure: root project files, `docs/`, ADR set, and `resync.toml` example.
- Added `docs/research-foundations.md`, `docs/competitive-landscape.md`, `docs/tech-stack.md`, and
  `docs/multi-language-adapters.md` — full detail behind what `architecture.md` summarizes.
- Added a per-directory `README.md` across `src/resync/`, `tests/`, `benchmarks/`, `examples/`, and `docs/`.
- Added baseline typed skeletons: `KnowledgeRecord`/`RuleType` (`knowledge/schema.py`), the `ResyncConfig`
  model set and loader (`config/`), the `LanguageAdapter` Protocol (`adapters/base.py`), `TrustScore`
  (`verification/trust_score.py`), the real-time gate tool signatures (`server/tools.py`), and the CLI command
  surface (`cli/main.py`). All raise `NotImplementedError` where logic isn't built yet — the point of this
  pass is a correct, typed interface surface, not a working implementation.
- `pyproject.toml`: moved contributor-only tooling to PEP 735 `[dependency-groups]`, keeping
  `[project.optional-dependencies]` for genuine user-facing extras only.
- Noted the OpenAI/Astral acquisition as a maintenance-risk watch item (see `docs/tech-stack.md`); no
  dependency changes made as a result, since `uv`/`ruff` remain the correct choice on current evidence.
