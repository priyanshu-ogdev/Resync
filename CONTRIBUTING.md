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

Any change that affects a core design decision — not an implementation detail — should come with an
Architecture Decision Record. Copy `docs/adr/0000-template.md`, number it sequentially, and reference it from
`docs/architecture.md` if it supersedes or extends an existing decision. This is how the project got the
decisions documented in `docs/adr/` in the first place, and it's how future contributors will understand *why*
something is built the way it is, not just *what* it does.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, etc.) —
`CHANGELOG.md` entries and release notes are generated from these.

## Pull requests

- Keep PRs scoped to one logical change. If a change spans both a mechanical fix and a design decision, split
  them — this is the same "sync vs. shift" separation of concerns the Impact Map design uses internally.
- New adapters (a new target language) should implement the five-function interface documented in
  `docs/architecture.md#multi-language-adapters` and include fixture tests before being merged.
