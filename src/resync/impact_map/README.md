# `impact_map/`

The sync-vs-shift decision layer — see `docs/architecture.md#the-impact-map` and the research it's built on
(Facebook's Getafix for mining a repo's own fix history, Google's Rosie infrastructure for sharding a
confirmed large-scale "sync" into small reviewable PRs). Not required for the initial milestone; depends on
the call/import graph and the verification layer both being stable first — see the build-priority table in
`docs/architecture.md`.

Elicitation for genuinely undecided cases goes through MCP's `input_required` mechanism, and every answer is
persisted via `config.loader.persist_policy` so the same case is never re-asked.
