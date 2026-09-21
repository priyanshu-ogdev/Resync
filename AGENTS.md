# AGENTS.md

Instructions for AI coding agents working in this repository. This is the open, cross-tool standard format
(governed by the Linux Foundation's Agentic AI Foundation, read natively by Claude Code, Codex CLI, Cursor,
Aider, Devin, Gemini CLI, and others) — put shared instructions here, not in a tool-specific file. If your
tool only reads a proprietary file (e.g. an older `CLAUDE.md`), keep that file a thin pointer to this one
rather than a fork of it — see `CLAUDE.md` at the repo root for that pattern.

## What this project is

Read `docs/PRD.md` (what and why) and `docs/architecture.md` (how) before making any non-trivial change. Do
not summarize or re-derive the design from the code alone — the docstrings and docs encode hard-won findings
from real testing that aren't otherwise visible in the code's current shape.

## Setup

```bash
# Automated one-way setup (background provisions uv, Python 3.12, ast-grep, and Resync):
./scripts/install.sh --local --dev                                          # Linux / macOS
.\scripts\install.exe --local --dev                                         # Windows

# Or manual:
uv sync --extra server --extra cli --group dev --group verify
uv run pre-commit install
```

## Build, test, lint

```bash
make test           # unit + integration
make lint            # ruff check
make format          # ruff format
make typecheck        # mypy
```

Or directly: `uv run pytest tests/unit`, `uv run pytest tests/integration` (requires the `ast-grep` binary
on `PATH`), `uv run ruff check .`, `uv run mypy src/`.

## The single most important convention in this codebase

**Verify against the real library or binary before writing code that calls it — do not assume an API from
memory or from documentation snippets alone.** This project's entire history (see
`docs/implementation-plan.md`'s Phase 1 and 2 status, and the module docstrings in `knowledge/store.py`,
`knowledge/graph_store.py`, and `patch/ast_grep_runner.py`) is a record of real bugs found specifically
*because* something was tested against a real instance instead of trusted on faith — including a bug that
would have crashed on the very first write to a fresh database. If you're adding a call to `lancedb`, `kuzu`,
`ast-grep`, or any other external tool, run it for real against a throwaway example first. A mocked unit test
alone is not sufficient evidence that new code touching these boundaries works.

## Tests that are supposed to fail-if-fixed

A small number of tests intentionally assert a known, permanent limitation rather than ideal behavior —
`tests/integration/test_ast_grep_runner.py::test_import_guard_does_not_catch_local_shadowing_this_is_a_known_residual_risk`
is the current example. Do not "fix" these by loosening the assertion; each has a docstring explaining
exactly what would need to be true (in this case, real scope resolution) before the test itself should
change. If you build that infrastructure, update the test and its docstring together, and update the
corresponding note in `docs/implementation-plan.md`.

One test that *used* to be in this category no longer is, and it's worth knowing the history rather than
just the current state: `test_ast_grep_runner.py::test_reorder_is_not_idempotent_this_is_a_known_limitation_not_a_bug_to_hide`
asserted that REORDER oscillates on repeated application, with a docstring saying it should keep failing
until an external applied-already guard was built. That guard was built (`config.schema.AppliedFix`,
`ast_grep_runner.apply(..., repo_root=...)`) — so the test was renamed to
`test_reorder_pattern_itself_is_still_not_idempotent_without_a_repo_root` and its docstring rewritten to
explain that the underlying ast-grep *pattern* is still not idempotent by design (that hasn't changed and
isn't meant to), while two new tests
(`test_reorder_apply_with_repo_root_is_safe_to_run_unattended_twice` and
`..._still_applies_a_genuinely_different_reorder`) now prove the guard itself works at the `apply()` layer,
which is where the real fix lives. If you ever see a reference to the old test name elsewhere in this repo's
docs, it's stale — this file is the canonical account of what changed and why.

## Where things live

- `src/resync/knowledge/` — retrieval (LanceDB + Kùzu-fork + fastembed), the `KnowledgeRecord` schema.
- `src/resync/patch/` — the deterministic (ast-grep) and taxonomy classification layer. Read
  `ast_grep_runner.py`'s module docstring in full before touching it — it documents ten distinct real,
  previously-shipped bugs and why each fix is shaped the way it is.
- `src/resync/config/` — `resync.toml` schema and I/O.
- `src/resync/verification/` — `tier.py`/`differential.py`/`trust_score.py`/`sandbox.py` are built and
  tested for three of four verification tiers (compile-check, deprecation-window-differential,
  oracle-signature-check); `critic.py` is a `Protocol` seam only, awaiting Phase 6's local-model-backed
- `src/resync/server/` — 5 production MCP tools (`tools.py` for verify_package/check_symbol_exists/explain_change/get_compatibility_report, `patch_verification.py` for verify_patch_equivalence), `app.py` (real MCP stdio/Streamable-HTTP transport wiring), and `dashboard.py` (Review Dashboard, AST unified diff preview, and live decision execution).
- `src/resync/cli/` — `main.py` (`run`, `check`, `explain`, `sync`, `serve`, `doctor`, `init`, `resolve`, `seed`, `ingest`, `mcp-config`), `scan.py` (AST symbol resolution and explainability cards), `mcp_config.py`, and `mcp_verify.py` (two-tier client verification).
- `src/resync/adapters/` — 7 built-in language adapters (Python, Rust, TypeScript, Kotlin, Java, Go, C/C++) with dynamic entry-point discovery and polyglot monorepo manifest detection (`registry.py`).
- `src/resync/llm/` — Phase 6's local-model-backed implementation (`generator.py`, `llama_server.py`) and critic model support.
- `src/resync/impact_map/` — interface and policy integration wired to `resync.toml` and Review Dashboard.
- `docs/architecture.md` (Section 4) — the authoritative record of architectural decisions (Decisions 1–6), with alternatives considered and consequences. Any significant architectural change must be documented here with full rationale; don't just change the code and leave the reasoning implicit.
- `tests/fixtures/` — every fixture's `NOTES.md` states whether it represents a real, cited change or a
  clearly-marked synthetic one. Never present an invented example as if it were verified.

## Code style

`ruff` (lint + format), `mypy --strict`. Python 3.11+. No `torch` dependency anywhere in the core package —
see `docs/tech-stack.md` for why that's a deliberate constraint, not an oversight.

## Before opening a PR

Run `make test lint typecheck`. If you touched `verification/` (once built), add a Hypothesis-based property
test, not just a fixed-input case — see `docs/architecture.md#7-testing-strategy--quality-pyramid` for why that layer specifically is held to
a higher bar than the rest of the codebase.
