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
