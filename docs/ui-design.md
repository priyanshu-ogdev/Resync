# UI design

Resync has three surfaces where a human actually looks at output, and they earn very different design
treatment because they're read in different contexts under different time pressure. This document covers all
three; a mockup of the richest one (the review dashboard) accompanies this document in the project's design
history.

## Design principles

- **Information density over polish.** This is a developer tool read by people mid-task, not a consumer app.
  Every surface favors scanability (tables, clear diff coloring, monospace for symbols) over whitespace for
  its own sake.
- **Color is semantic, never decorative.** Green means verified, amber means needs a human decision, red means
  blocked or failed. No color is used for visual variety alone — a screen that's mostly gray with occasional
  color is doing its job; a screen that's colorful everywhere has stopped meaning anything.
- **No surface hides the trust score.** Whichever of the three a person is looking at, the decomposed trust
  score from `docs/adr/0002` is visible, not buried behind a click — the whole point of decomposing it was to
  make the reasoning inspectable.

## Surface 1: CLI output

The `resync check`/`resync sync` commands (`cli/main.py`) use `rich` for terminal output — tables for
multi-item results, color-coded status (green/amber/red matching the semantics above), and a progress
indicator during the (potentially slow) semantic-verification path so a long-running differential-equivalence
check doesn't look like a hang. Package this as a dependency addition: `rich` belongs in the `cli` extra in
`pyproject.toml`.

## Surface 2: GitHub PR comments

Every PR Resync opens carries a comment with the decomposed trust score, not just a diff. Template:

```markdown
### Resync trust breakdown

| Signal | Result |
|---|---|
| Rule match | mechanical (rename) — 1.00 |
| Test suite | passed |
| Differential equivalence | passed (12 generated inputs, 0 divergent outputs) |
| Reviewer pass | n/a (mechanical fix, not LLM-drafted) |

**Change type:** `rename` &middot; **Source:** `cargo-semver-checks` diff of `mypackage` 2.1.0 → 2.2.0
```

For a sharded large-scale "sync" (`docs/architecture.md#the-impact-map`), each PR in the shard carries this
same template plus a link back to the parent decision record, so a reviewer looking at PR 4 of 12 can see it's
part of a larger, already-approved change rather than an isolated, unexplained diff.

## Surface 3: the review dashboard

Served as additional routes on the same Starlette application already running the MCP server's Streamable
HTTP transport (`docs/adr/0001`) — deliberately not a separate web framework or a client-side SPA build, to
stay consistent with the project's low-dependency-footprint philosophy (`docs/tech-stack.md`). Rendered with
Jinja2 templates and a small amount of vanilla JS; add `jinja2` to the `server` extra.

Three views:

1. **Pending decisions** — every Impact Map elicitation (`docs/architecture.md#the-impact-map`) currently
   waiting on a human answer, each showing the symbol, its change-type classification, blast radius (call
   sites and files affected), and a side-by-side diff preview of the "sync" and "shift" options with a button
   for each. This is the view mocked up in the project's design history: a stat row (pending decisions,
   auto-applied today, blocked by pin) above one expanded decision card with both options shown in full, and a
   compact list of additional pending items below it — deliberately not every pending item expanded at once,
   since the point of the dashboard is triage, not an undifferentiated wall of diffs.
2. **Recent changes** — a feed of applied changes with their trust-score breakdown, filterable by outcome
   (auto-applied, needs review, blocked).
3. **Pins and exceptions** — a read view of the current `resync.toml` pins, exceptions, and policies, with
   any exception's `expires` date highlighted in amber as it approaches, so the forced re-review this project's
   config design depends on (`docs/adr/0005`) is something a person is actually likely to notice, not just a
   field that technically exists.

The dashboard's "pending decisions" view can and should ship against mocked or fixture data before the Impact
Map's live decision logic exists — see `docs/implementation-plan.md#phase-7-delivery-and-ui` for why the UI
and the logic behind it are treated as separable work.

## What's deliberately not built

No mobile view, no user accounts, no multi-tenant access control on the dashboard for v0.1.0 — it's a local or
single-team tool running alongside a local MCP server, not a hosted product. Revisit if the remote/team
deployment mode (`docs/adr/0001`) becomes the primary way people run Resync rather than the local mode.
