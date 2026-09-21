"""Builds Resync's MCP server and wires verification tools and the patch-equivalence checker
up as real, callable MCP Tools.

Per docs/architecture.md#decision-1: one server binary, "local" vs. "server-based" is a transport
choice (stdio for a single developer, Streamable HTTP for a shared team deployment) on the same tool
implementations — not two separate designs. Built against `mcp>=2.0`, the SDK's stateless-core rewrite: the
old `mcp.server.fastmcp.FastMCP` class was renamed to `mcp.server.mcpserver.MCPServer` (confirmed against
this environment's actually-installed `mcp` package, not assumed from the `mcp>=1.0` pin that was still in
pyproject.toml — the exact gap that pin's own comment flagged and this pass now closes for real).

`repo_root` is resolved once, at server construction, rather than threaded through every MCP call: per
Decision 1 (docs/architecture.md#decision-1), the stdio transport is "a single trusted local caller" for
one developer's own checkout, so there is exactly one repo to check per running server process — an agent starts
`resync serve` from (or is pointed at) the repo it's working in, not a different one per tool call. This is a real,
load-bearing design choice, not an oversight: if multiple concurrent repos-per-process are ever needed (e.g. a future
shared HTTP deployment serving several repos), `repo_root` would need to move onto the MCP request/session instead —
flagged here rather than silently baked in as if it were the only possible design.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from resync.server.dashboard import attach_dashboard
from resync.server.patch_verification import PatchVerificationResult, verify_patch_equivalence
from resync.server.tools import (
    VerificationResult,
    check_symbol_exists,
    explain_change,
    get_compatibility_report,
    verify_package,
)

_REPO_ROOT_ENV_VAR = "RESYNC_REPO_ROOT"


def resolve_repo_root(explicit: Path | None = None) -> Path:
    """The repo this server instance checks. Priority: an explicit path (e.g. `resync serve --repo`), then
    the `RESYNC_REPO_ROOT` environment variable (for process managers/MCP client configs that set env vars
    rather than CLI args), then the current working directory the server was launched from — the common
    case for an agent that just ran `resync serve` inside the repo it's editing.

    Deliberately does *not* walk up looking for a `.git` directory: `config.loader.load()` already treats
    `repo_root / "resync.toml"` as optional (a missing file just means defaults), so over-searching upward
    risks silently attaching to the wrong repo if the server happens to be started from a subdirectory. Any
    of the three explicit sources above is an intentional signal; walking up is a guess.
    """
    if explicit is not None:
        return explicit.resolve()
    env_value = os.environ.get(_REPO_ROOT_ENV_VAR)
    if env_value:
        return Path(env_value).resolve()
    return Path.cwd().resolve()


def build_server(repo_root: Path | None = None) -> MCPServer:
    """Construct the MCPServer with the real-time gate tools registered
    (verify_package, check_symbol_exists, verify_patch_equivalence, explain_change, get_compatibility_report)
    and attach the review dashboard endpoints.

    `repo_root` here is already-resolved (see `resolve_repo_root`); this function takes the resolved value,
    not an "explicit override", so callers that already have a concrete path (tests, `resync check`) don't
    have to round-trip through env-var/cwd resolution just to override it.
    """
    resolved_root = repo_root if repo_root is not None else resolve_repo_root()
    server = MCPServer(
        name="resync",
        version="0.1.0",
        instructions=(
            "Call verify_package before adding a new import or dependency, and check_symbol_exists before "
            "calling a function from an existing dependency, to catch deprecated/removed/renamed APIs and "
            "known advisories before they land in code. Use explain_change to inspect root causes and options. "
            "See docs/architecture.md#decision-3-deterministic-first-patching."
        ),
    )

    @server.tool(
        name="verify_package",
        description=(
            "Check whether a package is safe to add as a new dependency: confirms it exists on the "
            "registry and has no known security advisories, honoring resync.toml pins/exceptions first."
        ),
    )
    def _verify_package(package: str, ecosystem: str = "pypi") -> VerificationResult:
        return verify_package(package, ecosystem, resolved_root)

    @server.tool(
        name="check_symbol_exists",
        description=(
            "Check whether a fully-qualified symbol (module.Class.method) has a known deprecation, "
            "removal, or rename affecting the given pinned version, honoring resync.toml pins/exceptions."
        ),
    )
    def _check_symbol_exists(fully_qualified_symbol: str, pinned_version: str) -> VerificationResult:
        return check_symbol_exists(fully_qualified_symbol, pinned_version, resolved_root)

    @server.tool(
        name="verify_patch_equivalence",
        description=(
            "After drafting your own rewrite of a call site affected by a known API change (using your own "
            "model — this tool does not draft anything itself), hand both the original and rewritten source "
            "here for a real, deterministic check against resync's knowledge store, rather than relying on "
            "your own self-assessment. Static checks only in this version — see the tool's own module "
            "docstring (server/patch_verification.py) for exactly what is and isn't verified."
        ),
    )
    def _verify_patch_equivalence(
        fully_qualified_symbol: str, old_source: str, new_source: str, pinned_version: str
    ) -> PatchVerificationResult:
        return verify_patch_equivalence(fully_qualified_symbol, old_source, new_source, pinned_version, resolved_root)

    @server.tool(
        name="explain_change",
        description=(
            "Provide deep explainability, root cause analysis, trust score breakdown, and remediation options "
            "([Sync], [Shift], [Pin], [Exception]) for an API change affecting a symbol or package."
        ),
    )
    def _explain_change(target: str, pinned_version: str | None = None) -> dict[str, Any]:
        return explain_change(target, resolved_root, pinned_version=pinned_version)

    @server.tool(
        name="get_compatibility_report",
        description=(
            "Generate a batch compatibility and explainability report across multiple dependencies or symbols, "
            "including decomposed trust scores, actionable options, and rich markdown formatting."
        ),
    )
    def _get_compatibility_report(items: list[str]) -> dict[str, Any]:
        return get_compatibility_report(items, resolved_root)

    # Attach interactive web dashboard and REST API routes to the Starlette HTTP server
    attach_dashboard(server, resolved_root)

    return server


def run(transport: str = "stdio", *, repo_root: Path | None = None, port: int = 8787) -> None:
    """Entry point used by `resync serve` (cli/main.py). `transport` is `"stdio"` or `"http"` at the CLI
    surface — mapped to the SDK's own `"stdio"` / `"streamable-http"` literals here, since the CLI's own
    flag help text (`stdio | http`) predates and is simpler than the SDK's internal naming, and there's no
    reason to leak that naming difference into the user-facing flag.
    """
    server = build_server(repo_root)
    if transport == "http":
        # stateless_http=True per ADR 0001: Resync's tools are single-shot request/response by design, with
        # no need for the SDK's session-affinity machinery, and stateless is what lets this deploy behind an
        # ordinary load balancer as the ADR describes.
        server.run(transport="streamable-http", port=port, stateless_http=True)
    else:
        server.run(transport="stdio")
