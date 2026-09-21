# Contributing to Resync

## Development setup

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency management — it resolves and installs
significantly faster than pip/Poetry, which matters for a project with this many moving pieces.

```bash
uv sync --extra server --extra cli --group dev
```

Extras are scoped deliberately (see `pyproject.toml`) so a contributor working only on the CLI doesn't have to
pull in the full server stack (LanceDB, the graph index, embeddings) — this is the same dependency-hygiene
principle the project itself enforces on the codebases it upgrades.

## Running tests

```bash
uv run pytest tests/unit
uv run pytest tests/integration    # requires the fixture repos under tests/fixtures
```

Any change to the patch or verification layers should include a Hypothesis-based property test where the
change affects correctness, not just a unit test for the happy path — see `docs/architecture.md#trust-and-verification-layer`
for why this project treats a passing test suite as necessary but not sufficient.

## Code style

Linting and formatting run through `ruff` (single tool, replaces flake8 + black + isort):

```bash
uv run ruff check .
uv run ruff format .
```

Type checking via `mypy` (or `ty`, if you've verified it's stable enough on your setup):

```bash
uv run mypy src/
```

## Architecture changes

Any change that affects a core design decision — not an implementation detail — should be documented with
its context, decision, alternatives considered, and consequences in `docs/architecture.md` (Section 4: Architectural Decisions & Rationale). This is how future contributors will understand *why* something is built the way it is, not just *what* it does.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, etc.) —
`CHANGELOG.md` entries and release notes are generated from these.

## Pull requests

- Keep PRs scoped to one logical change. If a change spans both a mechanical fix and a design decision, split
  them — this is the same "sync vs. shift" separation of concerns the Impact Map design uses internally.
- New adapters (a new target language) should implement the five-function interface documented in
  `docs/architecture.md#multi-language-adapters` and include fixture tests before being merged.

## Local pre-commit hooks

```bash
uv run pre-commit install
```

This runs `ruff` (lint + format) on every commit — the same checks CI runs, just earlier, so a PR doesn't
round-trip through CI to catch something `pre-commit` would have caught locally in a second.

## Codespaces / devcontainer

Opening this repo in a devcontainer (`.devcontainer/devcontainer.json`) installs `uv`, syncs dependencies, and
installs the pre-commit hooks automatically — useful for a consistent environment across contributors without
relying on everyone's local Python setup matching.
