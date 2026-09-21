"""Real, unmocked MCP-handshake coverage for cli/mcp_verify.py, matching this project's "zero-mock proof of
the core value proposition" standard (PRD §7): actual subprocesses, actual MCP client SDK, no stubbed
transport. Lives here rather than tests/unit because it spawns real child processes, per this project's own
unit/integration split.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

from resync.cli.mcp_verify import EXPECTED_TOOLS


def test_expected_tools_match_build_server_registrations() -> None:
    """If server/app.py's `build_server` ever adds/renames/removes a tool without a matching edit to
    `EXPECTED_TOOLS`, this fails loudly — the one place this module's fail-closed guarantee could otherwise
    go silently stale, per mcp_verify.py's own docstring warning.
    """
    from resync.server.app import build_server

    server = build_server(Path("."))
    registered = {tool.name for tool in server._tool_manager.list_tools()}  # type: ignore[attr-defined]
    assert registered == set(EXPECTED_TOOLS)


def test_verify_server_launch_against_a_real_trivial_mcp_server(tmp_path: Path) -> None:
    """No mocking of the MCP transport: a small real MCP server script is spawned as a real subprocess and
    handshook against using the real client SDK, exactly as `verify_server_launch` does against the real
    `resync serve` — proving the handshake logic works end-to-end, independent of whether resync's own
    (heavier) knowledge-layer dependencies happen to be installed in a given CI environment.
    """
    fake_server = tmp_path / "fake_server.py"
    fake_server.write_text(
        textwrap.dedent(
            """
            from mcp.server.mcpserver import MCPServer

            server = MCPServer(name="fake-resync", version="0.0.0")

            @server.tool(name="verify_package")
            def _verify_package(package: str, ecosystem: str = "pypi") -> dict:
                return {"ok": True}

            @server.tool(name="check_symbol_exists")
            def _check_symbol_exists(fully_qualified_symbol: str, pinned_version: str) -> dict:
                return {"ok": True}

            @server.tool(name="verify_patch_equivalence")
            def _verify_patch_equivalence(
                fully_qualified_symbol: str, old_source: str, new_source: str, pinned_version: str
            ) -> dict:
                return {"ok": True}

            @server.tool(name="explain_change")
            def _explain_change(target: str, pinned_version: str | None = None) -> dict:
                return {"ok": True}

            @server.tool(name="get_compatibility_report")
            def _get_compatibility_report(items: list[str]) -> dict:
                return {"ok": True}

            server.run(transport="stdio")
            """
        )
    )

    import resync.cli.mcp_verify as mcp_verify_module

    command = [sys.executable, str(fake_server)]
    result = mcp_verify_module.asyncio.run(mcp_verify_module._run_handshake(command, timeout=15.0))
    assert result.status == "verified", result.detail
    assert set(result.tools_found) == set(EXPECTED_TOOLS)


def test_verify_server_launch_fails_closed_when_a_tool_is_missing(tmp_path: Path) -> None:
    """A server that starts fine but is missing a tool must report 'failed', never 'verified' — the case a
    naive "did the process start" check would wrongly pass.
    """
    fake_server = tmp_path / "incomplete_server.py"
    fake_server.write_text(
        textwrap.dedent(
            """
            from mcp.server.mcpserver import MCPServer

            server = MCPServer(name="incomplete-resync", version="0.0.0")

            @server.tool(name="verify_package")
            def _verify_package(package: str, ecosystem: str = "pypi") -> dict:
                return {"ok": True}

            server.run(transport="stdio")
            """
        )
    )

    import resync.cli.mcp_verify as mcp_verify_module

    command = [sys.executable, str(fake_server)]
    result = mcp_verify_module.asyncio.run(mcp_verify_module._run_handshake(command, timeout=15.0))
    assert result.status == "failed"
    assert "check_symbol_exists" in result.missing_tools
    assert "verify_patch_equivalence" in result.missing_tools
