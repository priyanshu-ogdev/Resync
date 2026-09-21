"""Unit tests for cli/mcp_verify.py — command resolution and the fail-closed `HandshakeResult` contract.
Fast, no subprocess. The real end-to-end handshake tests (an actual MCP stdio server spawned and handshook
against, no mocked transport) live in tests/integration/test_mcp_verify_handshake.py, per this project's own
unit/integration split (see tests/README.md) rather than a custom pytest marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from resync.cli.mcp_verify import (
    HandshakeResult,
    _resolve_launch_command,
    _verify_claude_code,
    _verify_cursor,
    verify_client_config,
    verify_server_launch,
)


def test_handshake_result_ok_only_true_for_verified() -> None:
    assert HandshakeResult(status="verified", detail="x").ok
    assert not HandshakeResult(status="failed", detail="x").ok
    assert not HandshakeResult(status="unavailable", detail="x").ok


def test_resolve_launch_command_prefers_console_script_on_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("resync.cli.mcp_verify.shutil.which", lambda _name: "/usr/local/bin/resync")
    command = _resolve_launch_command(tmp_path)
    assert command is not None
    assert command[0] == "/usr/local/bin/resync"
    assert command[1:] == ["serve", "--transport", "stdio", "--repo", str(tmp_path)]


def test_resolve_launch_command_falls_back_to_module_invocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("resync.cli.mcp_verify.shutil.which", lambda _name: None)
    command = _resolve_launch_command(tmp_path)
    assert command is not None
    assert command[0] == sys.executable
    assert command[1:3] == ["-m", "resync.cli.main"]


def test_resolve_launch_command_none_when_resync_unimportable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("resync.cli.mcp_verify.shutil.which", lambda _name: None)

    real_import = __import__

    def _fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "resync.cli.main":
            raise ImportError("simulated: resync isn't installed in this interpreter")
        return real_import(name, *args, **kwargs)  # type: ignore[misc]

    monkeypatch.setattr("builtins.__import__", _fake_import)
    assert _resolve_launch_command(tmp_path) is None


def test_verify_server_launch_reports_unavailable_when_command_unresolvable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("resync.cli.mcp_verify._resolve_launch_command", lambda _root: None)
    result = verify_server_launch(tmp_path)
    assert result.status == "unavailable"
    assert not result.ok


def _fake_completed(stdout: str, stderr: str = "") -> object:
    import subprocess

    return subprocess.CompletedProcess(args=["fake"], returncode=0, stdout=stdout, stderr=stderr)


# --- Tier A: claude-code --------------------------------------------------------------------------------


def test_verify_claude_code_reports_verified_on_connected_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "resync.cli.mcp_verify._run_cli", lambda *a, **kw: _fake_completed("resync: ✓ Connected\nother: ✓ Connected\n")
    )
    result = _verify_claude_code(tmp_path, "resync", 5.0)
    assert result.status == "verified"
    assert result.tier == "A"


def test_verify_claude_code_reports_failed_with_flake_note_on_failed_to_connect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "resync.cli.mcp_verify._run_cli", lambda *a, **kw: _fake_completed("resync: ✗ Failed to connect\n")
    )
    result = _verify_claude_code(tmp_path, "resync", 5.0)
    assert result.status == "failed"
    assert "claude-code#21341" in result.detail


def test_verify_claude_code_unavailable_when_binary_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("resync.cli.mcp_verify._run_cli", lambda *a, **kw: None)
    result = _verify_claude_code(tmp_path, "resync", 5.0)
    assert result.status == "unavailable"


def test_verify_claude_code_failed_when_entry_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("resync.cli.mcp_verify._run_cli", lambda *a, **kw: _fake_completed("other: ✓ Connected\n"))
    result = _verify_claude_code(tmp_path, "resync", 5.0)
    assert result.status == "failed"


# --- Tier A: cursor ---------------------------------------------------------------------------------------


def test_verify_cursor_reports_verified_when_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("resync.cli.mcp_verify._run_cli", lambda *a, **kw: _fake_completed("resync: ready\n"))
    result = _verify_cursor(tmp_path, "resync", 5.0)
    assert result.status == "verified"
    assert result.tier == "A"


def test_verify_cursor_reports_unavailable_on_ci_approval_limitation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "resync.cli.mcp_verify._run_cli",
        lambda *a, **kw: _fake_completed("", 'Error: MCP server "resync" has not been approved'),
    )
    result = _verify_cursor(tmp_path, "resync", 5.0)
    assert result.status == "unavailable"


def test_verify_cursor_unavailable_when_binary_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("resync.cli.mcp_verify._run_cli", lambda *a, **kw: None)
    result = _verify_cursor(tmp_path, "resync", 5.0)
    assert result.status == "unavailable"


# --- Generalized dispatcher --------------------------------------------------------------------------------


def test_verify_client_config_uses_tier_a_when_available(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "resync.cli.mcp_verify.HEADLESS_VERIFIERS",
        {"claude-code": lambda root, name, timeout: HandshakeResult(status="verified", detail="tier a", tier="A")},
    )
    result = verify_client_config("claude-code", tmp_path)
    assert result.tier == "A"
    assert result.status == "verified"


def test_verify_client_config_falls_back_to_tier_b_when_tier_a_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "resync.cli.mcp_verify.HEADLESS_VERIFIERS",
        {"claude-code": lambda root, name, timeout: HandshakeResult(status="unavailable", detail="no cli", tier="A")},
    )
    monkeypatch.setattr(
        "resync.cli.mcp_verify.verify_server_launch",
        lambda root, **kw: HandshakeResult(status="verified", detail="tier b", tier="B"),
    )
    result = verify_client_config("claude-code", tmp_path)
    assert result.tier == "B"
    assert result.status == "verified"


def test_verify_client_config_goes_straight_to_tier_b_for_unlisted_clients(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "resync.cli.mcp_verify.verify_server_launch",
        lambda root, **kw: HandshakeResult(status="verified", detail="tier b only", tier="B"),
    )
    result = verify_client_config("zed", tmp_path)
    assert result.tier == "B"
