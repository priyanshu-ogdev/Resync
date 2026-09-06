# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioning follows
[Semantic Versioning 2.0.0](https://semver.org/).

## [Unreleased]

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
