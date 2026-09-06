# Release plan

## Versioning

Semantic Versioning 2.0.0, as already stated in `CHANGELOG.md`. Tags as `v0.1.0`. Conventional Commits
(`CONTRIBUTING.md`) drive changelog generation, so release notes are a byproduct of good commit hygiene, not a
separate manual writing task at release time.

## Publishing: PyPI Trusted Publishing, not a stored token

Use OIDC-based Trusted Publishing via `pypa/gh-action-pypi-publish`, the current PyPI-recommended standard —
no long-lived API token stored in repository secrets at all. Concretely:

1. Register the project on PyPI as a trusted publisher for this repository's `release.yml` workflow, scoped
   to a dedicated `pypi` GitHub Environment.
2. `release.yml` triggers on a published GitHub Release (not on every tag push, to keep an explicit human
   step between "tagged" and "published").
3. The job requests `id-token: write` permission and no username/password or token input — PyPI verifies the
   OIDC claim directly.
4. Build with `python -m build` (or `uv build`) producing both a wheel and an sdist before publishing.

This removes an entire class of release-time risk (a leaked or over-scoped PyPI token) that would otherwise
sit in repository secrets indefinitely.

## Pre-release checklist

- [ ] Confirm the final PyPI distribution name (`docs/tech-stack.md` — `resync-mcp` is the placeholder;
      verify availability, don't assume it).
- [ ] Replace every placeholder contact address in `SECURITY.md` and `CODE_OF_CONDUCT.md` with real ones.
- [ ] Run the project's own supply-chain provenance gate against its own dependencies
      (`docs/testing-strategy.md#verifying-the-release-itself`).
- [ ] Confirm `mcp`, `lancedb`, and the Kùzu-fork dependency are all pinned to versions verified against their
      current install docs, not assumed from earlier notes (`docs/adr/0004`).
- [ ] Re-run the full test suite, including the end-to-end demo-regression test, on a clean environment —
      not just a developer machine with a warm cache.
- [ ] Docs freeze: confirm `README.md`, `docs/architecture.md`, and `docs/workflow.md` describe what 0.1.0
      actually does, not what the roadmap says it will eventually do — a common and avoidable source of a
      confusing first-impression for new users.

## CI/CD workflow structure

- `.github/workflows/ci.yml` — runs on every PR: `ruff check`, `ruff format --check`, `mypy`, and the full
  test suite (unit, property-based, integration) across the supported Python matrix (3.11, 3.12).
- `.github/workflows/release.yml` — runs on a published GitHub Release: builds, runs the end-to-end
  demo-regression test one final time against the built artifact (not just source), then publishes via
  Trusted Publishing as above.

## Launch checklist

- [ ] Tag `v0.1.0`, publish the GitHub Release with changelog notes generated from Conventional Commits.
- [ ] Record the flagship demo scenario (`docs/architecture.md#flagship-demo`) as a short video — the same
      script used for the end-to-end regression test doubles as the launch demo, so it's already rehearsed
      and already known to work.
- [ ] Publish the release announcement referencing the specific, cited gaps this project closes
      (`docs/competitive-landscape.md`) rather than generic claims — the differentiation argument is strongest
      when it's specific.
- [ ] Open GitHub Milestones for the explicitly-deferred roadmap items (TypeScript/Rust adapters, the Impact
      Map's live logic, the breaking-change manifest standard, DepMigrationBench) so "not yet built" reads as
      a plan, not an omission.

## Post-release

- Triage incoming issues against the risk categories in `docs/architecture.md#risks-and-mitigations` first —
  a report that a pin was ignored or a false negative slipped through the verification layer is a different
  severity class than a CLI ergonomics complaint, and should be labeled accordingly from the start.
- Revisit the `ty` type-checker decision (`docs/tech-stack.md`) once it reaches a stable release and the
  post-acquisition Astral situation has settled, rather than on a fixed calendar date.
