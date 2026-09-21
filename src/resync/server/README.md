# `server/`

The MCP server — see `docs/architecture.md#decision-1-single-mcp-server-with-transport-duality` for why this is one server with a transport
choice (stdio for local, Streamable HTTP for remote/team use), not two designs. Built against the 2026-07-28
stateless MCP core.

- `tools.py` — the real-time gate: `verify_package`, `check_symbol_exists`. These must stay fast lookups, never
  LLM calls — a call has to return before the calling agent's next token.

Guardrails (resync.toml pins/exceptions) are enforced inside these tool functions directly, per
`docs/architecture.md#decision-3-deterministic-first-patching` — never left as a prompt instruction.
