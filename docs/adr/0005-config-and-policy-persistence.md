# ADR 0005: `resync.toml` as the single source of truth for pins, exceptions, and persisted decisions

**Status:** accepted

## Context

Not every part of a codebase should be auto-upgraded: hardware constraints, downstream compatibility
requirements, and deliberately-frozen legacy code all need a way to opt out of automated fixes without being
repeatedly flagged as bugs. Separately, the Impact Map (see `docs/architecture.md#the-impact-map`) sometimes
needs a human decision between propagating a fix uniformly ("sync") or using it as an opportunity to modernize
a whole usage pattern ("shift") — and re-asking that question every time an equivalent case recurs would be
worse than the PR-fatigue problem this project set out to avoid in the first place.

## Decision

A single `resync.toml` at the repo root, sitting alongside `pyproject.toml`/`package.json` rather than as a
hidden dotfile, holds four kinds of entries: project-level mode and scheduling, `[[pin]]` (package/symbol
version ceilings with a reason), `[[exception]]` (file/symbol-level frozen code with a mandatory `expires`
date so an exception can't silently become permanent tech debt), and `[[policy]]` (persisted sync-vs-shift
decisions from the Impact Map). All pin/exception checks happen *before* a potential issue is flagged, not
after — so intentionally-frozen code never appears in a trust dashboard as a false positive in the first
place. Pair the file with an inline pragma (`# resync: pin reason="..."`) for finer-grained, in-context control,
deliberately mirroring the shape of `# noqa` and `# type: ignore`, conventions developers already trust,
rather than inventing a new one.

## Alternatives considered

- **A database or hosted config service instead of a repo-committed file** — rejected: a config that isn't
  version-controlled alongside the code it governs loses the audit trail and can drift out of sync with the
  repository's actual state.
- **No `expires` field on exceptions** — rejected: without a forced re-review date, exceptions accumulate
  indefinitely and the "we know it's deprecated but can't upgrade yet" mechanism becomes exactly the kind of
  silently-ignored warning list this project exists to prevent.
- **Re-asking the sync-vs-shift question every time** — rejected as the default behavior; this is what the
  `[[policy]]` persistence mechanism specifically exists to avoid.

## Consequences

Any tool or agent integration must read `resync.toml` before evaluating a potential change, which adds a
required parsing step to every code path, not an optional one. The `expires` field requires an operational
habit (someone has to act on an expiring exception) that the tool itself cannot fully enforce — it can only
surface the expiry, not force a resolution.

## References

- `# noqa` / `# type: ignore` — the existing developer convention this project's inline pragma deliberately
  mirrors.
- The Impact Map design (`docs/architecture.md`), which motivates the `[[policy]]` persistence mechanism.
