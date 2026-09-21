"""Integration coverage for `resync mcp-config` / `resync mcp-config-list` / `resync mcp-config custom`,
driven through Typer's CliRunner — the real CLI entrypoint.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from resync.cli.main import app


def test_mcp_config_writes_a_real_client_file(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "cursor", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    written = tmp_path / ".cursor" / "mcp.json"
    assert written.exists()
    assert "resync" in json.loads(written.read_text())["mcpServers"]


def test_mcp_config_zed_writes_the_real_nested_shape(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "zed", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    written = json.loads((tmp_path / ".zed" / "settings.json").read_text())
    assert written["context_servers"]["resync"]["command"]["path"] == "resync"


def test_mcp_config_print_flag_never_writes_a_file(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "vscode", "--repo", str(tmp_path), "--print"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".vscode").exists()
    assert '"type": "stdio"' in result.output


def test_mcp_config_antigravity_never_writes_and_shows_guidance(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "antigravity", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Manage MCP Servers" in result.output
    assert not any(tmp_path.rglob("*"))


def test_mcp_config_verify_flag_runs_a_real_handshake(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`--verify` should call through to mcp_verify.verify_client_config and surface its result — patched
    here (rather than spawning the full real server, which needs the heavier knowledge-layer deps) to keep
    this a fast CLI-wiring test; the handshake logic itself is proven for real in
    tests/integration/test_mcp_verify_handshake.py.
    """
    from resync.cli.mcp_verify import HandshakeResult

    monkeypatch.setattr(
        "resync.cli.mcp_verify.verify_client_config",
        lambda _client, _root, **_kw: HandshakeResult(
            status="verified", detail="ok", tools_found=("a", "b", "c"), tier="B"
        ),
    )
    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "cursor", "--repo", str(tmp_path), "--verify"])
    assert result.exit_code == 0, result.output
    assert "Verified" in result.output


def test_mcp_config_verify_flag_exits_nonzero_on_failed_handshake(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from resync.cli.mcp_verify import HandshakeResult

    monkeypatch.setattr(
        "resync.cli.mcp_verify.verify_client_config",
        lambda _client, _root, **_kw: HandshakeResult(status="failed", detail="tool missing", tier="B"),
    )
    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "cursor", "--repo", str(tmp_path), "--verify"])
    assert result.exit_code == 1
    assert "Failed" in result.output


def test_mcp_config_verify_flag_reports_tier_a_when_client_was_actually_asked(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Confirms the CLI surfaces which tier produced the result, so a passing --verify for Claude Code/
    Cursor is visibly stronger evidence than one that fell back to the direct-spawn check."""
    from resync.cli.mcp_verify import HandshakeResult

    monkeypatch.setattr(
        "resync.cli.mcp_verify.verify_client_config",
        lambda _client, _root, **_kw: HandshakeResult(
            status="verified", detail="claude mcp list confirms: resync: ✓ Connected", tier="A"
        ),
    )
    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "claude-code", "--repo", str(tmp_path), "--verify"])
    assert result.exit_code == 0, result.output
    assert "asked the real client" in result.output


def test_mcp_config_unknown_client_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "totally-fake-client"])
    assert result.exit_code == 2
    assert "Unknown client" in result.output


def test_mcp_config_custom_produces_a_snippet_and_writes_nothing(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "mcp-config",
            "custom",
            "--root-key",
            "mcpServers",
            "--command-style",
            "separate",
            "--repo",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"mcpServers"' in result.output
    assert not any(tmp_path.rglob("*"))


def test_mcp_config_custom_rejects_unknown_command_style() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "custom", "--command-style", "bogus"])
    assert result.exit_code == 2
    assert "Unknown --command-style" in result.output


def test_mcp_config_custom_supports_array_style_and_type_value() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "mcp-config",
            "custom",
            "--root-key",
            "mcp",
            "--command-style",
            "array",
            "--type-value",
            "local",
        ],
    )
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output.split("\n\n")[0])
    assert doc["mcp"]["resync"]["type"] == "local"
    assert doc["mcp"]["resync"]["command"] == ["resync", "serve", "--transport", "stdio"]


def test_mcp_config_custom_name(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["mcp-config", "custom", "--root-key", "mcpServers", "--command-style", "separate", "--name", "x"]
    )
    assert result.exit_code == 0, result.output
    assert '"x"' in result.output


def test_mcp_config_list_shows_every_registered_client() -> None:
    from resync.cli.mcp_config import CLIENT_IDS

    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config-list"])
    assert result.exit_code == 0, result.output
    for client in CLIENT_IDS:
        assert client in result.output


def test_mcp_config_merges_into_a_real_pre_existing_file(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text(json.dumps({"mcpServers": {"github": {"command": "docker", "args": []}}}))

    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "cursor", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output

    written = json.loads((cursor_dir / "mcp.json").read_text())
    assert "github" in written["mcpServers"]
    assert "resync" in written["mcpServers"]


def test_mcp_config_auto_detects_and_configures_present_agents(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text(json.dumps({"mcpServers": {}}))

    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config-auto", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Configured AI Coding Agents" in result.output
    assert "Cursor" in result.output

    written = json.loads((cursor_dir / "mcp.json").read_text())
    assert "resync" in written["mcpServers"]


def test_mcp_config_auto_all_scaffolds_and_updates_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(".vscode/\n.cursor/\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config-auto", "--all", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".vscode" / "mcp.json").exists()
    assert (tmp_path / ".cursor" / "mcp.json").exists()
    assert (tmp_path / ".mcp.json").exists()
    assert (tmp_path / ".agents" / "mcp_config.json").exists()
    assert (tmp_path / ".zed" / "settings.json").exists()

    gitignore_content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "!.vscode/mcp.json" in gitignore_content
    assert "!.cursor/mcp.json" in gitignore_content


def test_mcp_config_scaffold_creates_team_templates(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(".vscode/\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config-scaffold", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Team MCP Configuration Templates Scaffolded" in result.output

    # Check each scaffolded template
    vscode_cfg = json.loads((tmp_path / ".vscode" / "mcp.json").read_text())
    assert "resync" in vscode_cfg["servers"]
    assert vscode_cfg["servers"]["resync"]["type"] == "stdio"

    cursor_cfg = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    assert "resync" in cursor_cfg["mcpServers"]

    claude_cfg = json.loads((tmp_path / ".mcp.json").read_text())
    assert "resync" in claude_cfg["mcpServers"]

    antigravity_cfg = json.loads((tmp_path / ".agents" / "mcp_config.json").read_text())
    assert "resync" in antigravity_cfg["mcpServers"]

    zed_cfg = json.loads((tmp_path / ".zed" / "settings.json").read_text())
    assert "resync" in zed_cfg["context_servers"]

    gitignore_content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "!.vscode/mcp.json" in gitignore_content


def test_mcp_config_auto_alias_delegates_cleanly(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text(json.dumps({"mcpServers": {}}))

    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "auto", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    normalized = " ".join(result.output.split())
    assert "alias for 'resync mcp-config-auto'" in normalized
    assert "Configured AI Coding Agents" in result.output


def test_mcp_config_list_alias_delegates_cleanly() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["mcp-config", "list"])
    assert result.exit_code == 0, result.output
    normalized = " ".join(result.output.split())
    assert "alias for 'resync mcp-config-list'" in normalized
    assert "Registered MCP client formats" in result.output
