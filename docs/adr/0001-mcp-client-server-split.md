# ADR 0001: Ship Resync as an MCP server, with local and remote as a transport choice

**Status:** accepted

## Context

Resync needs to expose its knowledge base and verification tools to multiple, heterogeneous AI coding agents
(Claude Code, OpenCode, Google Antigravity, and others), and to support both a single developer running
everything on one machine and a team sharing one always-on knowledge base. Building a bespoke integration per
agent creates an N-by-M maintenance problem: every agent needs custom code for every tool, and every tool needs
custom code for every agent, and that matrix grows faster than any team can maintain.

## Decision

Resync is a single MCP server. "Local" and "server-based" are a transport choice on the same binary — stdio for
a single-user local process, Streamable HTTP for a shared, always-on team server — not two separate designs.
Build against the MCP specification revision of 2026-07-28, which replaced the old stateful handshake with a
stateless core: a tool call needing mid-flight input returns `resultType: "input_required"` and is resent with
the answer, rather than holding an open bidirectional stream. This suits Resync's real-time gate particularly
well, since it is single-shot request/response by nature and needs no session affinity to deploy behind an
ordinary load balancer.

Ship a companion Agent Skill alongside the MCP server: MCP provides the capability (call a tool, get an
answer), while a Skill (a lazily-loaded markdown instruction file) teaches an agent when and how to reach for
that capability. This covers agents that support Skills but haven't wired up Resync's MCP server directly.

## Alternatives considered

- **A bespoke REST API per agent integration** — rejected: recreates the N-by-M problem MCP exists specifically
  to solve, and none of the target agents would consume it without custom glue code.
- **A single fixed transport (stdio only, or HTTP only)** — rejected: stdio-only would rule out team/shared use;
  HTTP-only would add unnecessary network-hop latency and infrastructure requirements for a single developer's
  local workflow.
- **Building against the pre-2026-07-28 stateful MCP core** — rejected: that transport model is on a
  deprecation path, and the stateless core is a better architectural fit for Resync's fast-lookup gate anyway.

## Consequences

One server binary serves both use cases, which simplifies maintenance but means the server's tool
implementations must be written defensively enough to handle both a single trusted local caller and multiple
concurrent remote clients. The dependency on a specification that revised significantly in mid-2026 means the
MCP SDK version must be tracked carefully — see `pyproject.toml`'s note to confirm the `mcp` package version
targets the current spec before pinning.

## References

- MCP specification revision, 2026-07-28 (stateless core, removal of Roots/Sampling/Logging as core primitives).
- "Skills vs MCP: How AI Tools Have Evolved" — the capability/know-how framing adopted here.
- Google's Dependency Director (July 2026) — reviewed as the closest prior art using a similar agent-integration
  model; see `docs/architecture.md` and ADR 0002 for what it does differently.
