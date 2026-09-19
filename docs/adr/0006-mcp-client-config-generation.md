# ADR 0006: MCP client config generation via a declarative registry, not per-client code

**Status:** accepted

## Context

`resync serve` speaks MCP, and any compliant client — Claude Desktop, Claude Code, Cursor, VS Code, OpenCode,
Windsurf, Zed, Antigravity, or anything else built against the same protocol — can call its tools once it
knows to. But "once it knows to" turned out to hide real, substantial per-client variation: this is not one
JSON shape with cosmetic renaming across clients. Live research (2026-09) into how each client's own,
current documentation and real bug trackers describe adding an MCP server found **four genuinely different
config shapes** across eight clients:

1. `{"mcpServers": {name: {"command", "args", "env"}}}` — Claude Desktop, Claude Code, Cursor, Windsurf,
   Antigravity.
2. `{"servers": {name: {"type": "stdio", "command", "args", "env"}}}` — VS Code. Different root key, and an
   *explicitly required* `type` field (VS Code does not infer the transport from which keys are present,
   unlike every client in group 1).
3. `{"mcp": {name: {"type": "local", "command": [...], "environment": {...}, "enabled": true}}}` — OpenCode.
   Different root key, one combined command array instead of separate `command`/`args`, and the env-var key
   is `environment`, not `env`.
4. `{"context_servers": {name: {"command": {"path", "args"}}}}` — Zed. Different root key again, and
   command/args are nested *inside* a `command` object rather than being sibling keys.

Beyond the JSON shape itself, real per-client differences also showed up in *where* the file lives: some
clients support a project-level file (team-shareable, checked into version control), some are global-only
(Windsurf), and Claude Desktop specifically reads a *different file entirely* from Claude Code, despite the
similar product name (confirmed explicitly by multiple current, independent sources). Two real, currently-
open client bugs were also found during this research and needed to be designed around, not just noted:
Claude Desktop deletes its entire `mcpServers` section on startup if it finds a `url`-based (remote) entry
(anthropics/claude-code#37286), and OpenCode's `environment` field is confirmed, in some versions, to not
actually reach the spawned child process (anomalyco/opencode#26332).

Finally, and most importantly for the design decision below: **this space moves fast, and independently per
client.** Antigravity's own config file path was found to be genuinely unsettled across multiple credible,
mutually-conflicting sources describing its Desktop/IDE/CLI surfaces and recent version history — not a gap
in this research, but a real, current state of flux in the product itself. Any of the eight clients above
could change its own format on its own schedule, for reasons that have nothing to do with resync.

## Decision

Represent each client as a `ClientSpec` (a plain dataclass: root key, command style, whether/what `type`
value, env-var key name, extra fields, path resolver, a `last_verified` date, and free-text `notes` for known
caveats) in a `REGISTRY` dict, and drive all generation through one generic `build_entry()` function
parameterized by those fields — rather than an `if client == "x": ...` branch per client hand-assembling its
own JSON. Concretely, `resync mcp-config <client>` merges (never overwrites) resync's entry into that
client's real file; `resync mcp-config-list` surfaces every registered client's `last_verified` date and
`notes` so a person can judge for themselves whether a listed format might have drifted since (this project
has no way to check that against a live schema registry — none exists for MCP client configs); and
`resync mcp-config custom --root-key ... --command-style ... [--type-value ...]` is a first-class escape
hatch for any MCP-compliant agent not yet in `REGISTRY` — built on the same real invariant that makes MCP a
standard at all: every compliant client accepts some command/args/env triple, so the three `command_style`
values (`separate`/`array`/`nested_object`, extendable if a fifth real shape is ever found) already cover any
future client's shape, parameterized from the CLI rather than requiring a resync release first.

Antigravity's `path_resolver` is deliberately `None` — `write_config` refuses to write for a client whose
spec has no resolver, and the CLI instead prints the (well-corroborated) JSON shape and directs the person to
Antigravity's own in-app "Manage MCP Servers → View/Open raw config" UI. Guessing one path out of several
credible, conflicting candidates would risk silently writing to a file that particular Antigravity surface or
version doesn't actually read — worse than admitting the uncertainty.

## Alternatives considered

- **One `if/elif` chain per client, inline in the CLI command.** Rejected: this is exactly the code shape
  that gets harder to trust with every client added, and — the more important property for a genuinely
  moving target — harder to *patch quickly* when one client changes its format on its own schedule. A
  one-line data edit to a `ClientSpec` is a smaller, more reviewable, more confidently-shippable change than
  a new branch inside a larger function.
- **MCP Sampling, to have the connected client generate its own config.** Not applicable here at all —
  Sampling is for delegating an LLM *completion* to the client, not for reading the client's own file-system
  conventions, and it's deprecated as of MCP spec revision 2026-07-28 regardless (confirmed live; see
  `docs/architecture.md`'s note on the same point for the semantic-tier generator/critic design).
  Config-format knowledge has to live in resync itself, or not exist at all.
- **Guessing Antigravity's file path from the most-cited source.** Rejected once the research showed the
  citations themselves disagree, correlated with real, recent product-surface/version differences (Desktop
  vs. IDE vs. CLI, and a version bump in between) rather than one source simply being wrong. A wrong guess
  here is worse than no guess: it produces a file the person reasonably assumes worked, that Antigravity
  silently never reads.
- **A single universal shape, asking every client to accept it.** Not resync's choice to make — these are
  independently-designed, already-shipped products; the shapes described above are simply what each one's
  own current documentation and source confirm it actually reads.

## Consequences

Adding a ninth client (or a client changing its tenth format) is now a `ClientSpec` entry plus its research
citations in `notes`, not new control flow — lower risk to review, and the generic `build_entry()` shape-
interpreter is exercised (and tested) the same way regardless of how many clients use it. The `custom`
escape hatch means an entirely unlisted, brand-new agent is usable on day one, at the cost of the person
needing to know (from that agent's own docs) its root key and command style themselves — a reasonable trade,
since resync cannot know about an agent that didn't exist when this was written.

The explicit `last_verified` dates and `notes` are an honest admission that this module cannot detect format
drift on its own, not a substitute for it. A stale entry will look identical to a current one until someone
notices a generated config stops working and checks `resync mcp-config-list`'s notes — this is a real,
accepted limitation, not a solved problem, and the right long-term fix (if it ever emerges) would be
consuming an upstream, machine-readable registry of client config schemas, which does not exist today.

## References

- MCP spec, Sampling deprecation: revision 2026-07-28, SEP-2577 ("new implementations SHOULD NOT adopt it").
- Claude Desktop `url`-entry data-loss bug: anthropics/claude-code#37286.
- OpenCode `environment` field not reaching the child process: anomalyco/opencode#26332.
- Zed's `context_servers`/nested `command` object shape: Zed's own client-setup documentation (real
  worked example with `"command": {"path": "npx", "args": [...]}}`).
- VS Code's explicit `"type"` requirement and `"servers"` root key: VS Code's current MCP developer guide.
- OpenCode's `mcp` root key, array-style `command`, and `environment` key: multiple independent, current
  community and vendor documentation sources, cross-checked against each other.
