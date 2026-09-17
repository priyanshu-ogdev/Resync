# Resync

**An AI-native compatibility engine for dependencies, APIs, and the agents that write your code.**

Resync keeps a codebase's dependencies and API usage synchronized with reality — for code an AI agent is about to write (real-time prevention) and for code that has already drifted out of date (scheduled, risk-tiered correction) — backed by a differential/property-based behavioral-equivalence check instead of "the tests passed."

Requirements and scope: [`docs/PRD.md`](docs/PRD.md). Full design rationale: [`docs/architecture.md`](docs/architecture.md). End-to-end flow: [`docs/workflow.md`](docs/workflow.md). Individual decisions and their trade-offs: [`docs/adr/`](docs/adr/). Working in this repo with an AI coding agent: [`AGENTS.md`](AGENTS.md).

## Why

Two failure modes motivate this project, both documented in [`docs/architecture.md`](docs/architecture.md#the-problem):

- **Old code rots** — libraries deprecate and remove APIs, and codebases quietly accumulate calls into functions no longer present in the pinned version.
- **New code is born broken** — AI coding agents hallucinate package names and deprecated API calls at measured, documented rates ("slopsquatting").

Resync targets both with one knowledge base: a real-time MCP gate for agents writing new code, and a scheduled sweep for code that's already there.

## Status

Early scaffold. See [`CHANGELOG.md`](CHANGELOG.md) for what's implemented versus planned, and the build-priority table in [`docs/architecture.md`](docs/architecture.md#build-priority) for what's in scope for the current milestone.

## Quickstart

```bash
# install uv if you don't have it: https://docs.astral.sh/uv/
uv sync --extra server --extra cli --group dev
uv run resync --help
```

Configuration lives in [`resync.toml`](resync.toml) at the repo root of whichever project Resync is pointed at — see that file for a fully commented example, including pins, exceptions, and persisted sync/shift policies.

## Repository layout

```
src/resync/        core package (server, knowledge, adapters, patch, verification, impact_map, config, cli)
skills/resync/      companion Agent Skill (SKILL.md)
docs/               PRD, architecture, workflow, and architecture decision records (ADRs)
tests/              unit, integration, and fixture repos
benchmarks/         reserved for a future public migration-correctness benchmark
examples/           example resync.toml configurations
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Significant architectural changes should come with an ADR — see [`docs/adr/0000-template.md`](docs/adr/0000-template.md).

## Security

See [`SECURITY.md`](SECURITY.md) for how to report a vulnerability.

## License

[MIT](LICENSE).
