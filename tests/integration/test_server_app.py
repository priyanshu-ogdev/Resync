"""Integration coverage for server/app.py — confirms verify_package/check_symbol_exists are reachable as
real MCP Tools through the actual mcp SDK's `MCPServer.call_tool`, not just as plain Python functions.

Uses a pinned package/symbol for both tools so this test needs no live network and no seeded knowledge
store — that combination is already covered by tests/unit/test_verify_package.py (httpx.MockTransport) and
tests/integration/test_check_symbol_exists.py (a real seeded LanceDB table). What's new and load-bearing
here is proving the MCP *registration and call plumbing* itself works end-to-end: right tool names, right
argument schema, right return shape — none of which the lower-level function tests can catch, since they
call the plain Python functions directly and never go through the SDK at all.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from resync.server.app import build_server, resolve_repo_root


@pytest.fixture
def pinned_repo(tmp_path: Path) -> Path:
    (tmp_path / "resync.toml").write_text(
        '[[pin]]\npackage = "legacy-pkg"\nmax_version = "1.0.0"\nreason = "frozen"\n\n'
        '[[pin]]\npackage = "legacy.old_call"\nmax_version = "1.0.0"\nreason = "frozen"\n'
    )
    return tmp_path


def test_both_tools_are_registered_with_the_documented_names(pinned_repo: Path) -> None:
    """Three tools now, not two — verify_patch_equivalence added alongside the original real-time-gate
    pair. Updated rather than left asserting the pre-expansion set, per this project's own convention of
    correcting a stale test to match reality."""
    server = build_server(pinned_repo)
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {"verify_package", "check_symbol_exists", "verify_patch_equivalence"}


def test_verify_package_reachable_through_the_real_mcp_call_path(pinned_repo: Path) -> None:
    """Goes through MCPServer.call_tool (the exact path a real MCP client uses), not verify_package()
    directly — a pinned package short-circuits before any network call, so this needs no live network."""
    server = build_server(pinned_repo)
    result = asyncio.run(server.call_tool("verify_package", {"package": "legacy-pkg", "ecosystem": "pypi"}))
    assert result.is_error is not True
    payload = "".join(getattr(block, "text", "") for block in result.content)
    assert "pinned" in payload.lower()


def test_check_symbol_exists_reachable_through_the_real_mcp_call_path(pinned_repo: Path) -> None:
    server = build_server(pinned_repo)
    result = asyncio.run(
        server.call_tool(
            "check_symbol_exists",
            {"fully_qualified_symbol": "legacy.old_call", "pinned_version": "0.9.0"},
        )
    )
    assert result.is_error is not True
    payload = "".join(getattr(block, "text", "") for block in result.content)
    assert "pinned" in payload.lower()


def test_verify_patch_equivalence_reachable_through_the_real_mcp_call_path(pinned_repo: Path) -> None:
    server = build_server(pinned_repo)
    result = asyncio.run(
        server.call_tool(
            "verify_patch_equivalence",
            {
                "fully_qualified_symbol": "legacy.old_call",
                "old_source": "legacy.old_call(x=1)",
                "new_source": "legacy.old_call(x=1)",
                "pinned_version": "0.9.0",
            },
        )
    )
    assert result.is_error is not True
    payload = "".join(getattr(block, "text", "") for block in result.content)
    assert "pinned" in payload.lower()


def test_resolve_repo_root_prefers_explicit_then_env_then_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    env_dir = tmp_path / "from-env"
    env_dir.mkdir()

    assert resolve_repo_root(explicit) == explicit.resolve()

    monkeypatch.delenv("RESYNC_REPO_ROOT", raising=False)
    monkeypatch.setenv("RESYNC_REPO_ROOT", str(env_dir))
    assert resolve_repo_root() == env_dir.resolve()

    monkeypatch.delenv("RESYNC_REPO_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert resolve_repo_root() == tmp_path.resolve()
