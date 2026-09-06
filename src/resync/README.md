# `resync` package

The core implementation, organized to mirror `docs/architecture.md` one module per major component. Nothing
in this package should branch on a specific language by name outside `adapters/` — that boundary is what keeps
the multi-language design (`docs/multi-language-adapters.md`) honest.

| Module | Responsibility |
|---|---|
| `server/` | The MCP server: real-time gate tools, transport, schema |
| `knowledge/` | The knowledge-record schema and hybrid retrieval (vector, graph, router) |
| `adapters/` | Per-language plugins implementing the five-function interface |
| `patch/` | Signature-change taxonomy and the ast-grep-based deterministic patch layer |
| `verification/` | Trust scoring, differential/property-based equivalence checking, sandboxing |
| `impact_map/` | Call-graph clustering and sync-vs-shift policy persistence |
| `config/` | `resync.toml` schema, loading, and writing |
| `cli/` | The offline-first command-line entry point |
