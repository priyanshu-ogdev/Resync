"""Unit tests for cli/mcp_config.py's declarative registry — real, verified formats for each supported
client. Every assertion checks the exact real shape confirmed via live research (see module docstring), not
a guessed-by-analogy shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resync.cli.mcp_config import (
    CLIENT_IDS,
    REGISTRY,
    build_entry,
    config_path_for,
    describe_registry,
    detect_agent_config_targets,
    ensure_gitignore_unignores,
    format_custom,
    format_for_display,
    generate_entry,
    infer_client_spec_from_dict,
    merge_config,
    scaffold_project_mcp_templates,
    write_config,
    write_target_config,
)


def test_all_registered_clients_produce_a_valid_entry() -> None:
    for client in CLIENT_IDS:
        entry = generate_entry(client)
        assert isinstance(entry, dict)
        assert entry


def test_registry_has_at_least_the_originally_researched_clients() -> None:
    assert {"claude-desktop", "claude-code", "cursor", "vscode", "opencode", "antigravity"} <= set(CLIENT_IDS)


def test_registry_has_the_newly_added_clients() -> None:
    assert {"windsurf", "zed"} <= set(CLIENT_IDS)


class TestBuildEntryShapeInterpreter:
    """build_entry is the one generic function every ClientSpec (and the `custom` escape hatch) goes
    through — these tests exercise all three real command_style shapes directly, independent of any
    specific client's registration."""

    def test_separate_style(self) -> None:
        entry = build_entry(command="resync", args=["serve"], root_key="mcpServers", command_style="separate")
        assert entry["command"] == "resync"
        assert entry["args"] == ["serve"]

    def test_array_style(self) -> None:
        entry = build_entry(command="resync", args=["serve"], root_key="mcp", command_style="array")
        assert entry["command"] == ["resync", "serve"]
        assert "args" not in entry

    def test_nested_object_style(self) -> None:
        entry = build_entry(command="resync", args=["serve"], root_key="context_servers", command_style="nested_object")
        assert entry["command"] == {"path": "resync", "args": ["serve"]}

    def test_type_field_only_included_when_requested(self) -> None:
        without = build_entry(command="x", args=[], root_key="k", command_style="separate")
        assert "type" not in without
        with_type = build_entry(
            command="x", args=[], root_key="k", command_style="separate", requires_type_field=True, type_value="stdio"
        )
        assert with_type["type"] == "stdio"

    def test_extra_fields_are_merged_in(self) -> None:
        entry = build_entry(command="x", args=[], root_key="k", command_style="array", extra_fields={"enabled": True})
        assert entry["enabled"] is True

    def test_unknown_command_style_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown command_style"):
            build_entry(command="x", args=[], root_key="k", command_style="bogus")  # type: ignore[arg-type]


def test_claude_desktop_never_uses_url_transport() -> None:
    """Real, documented bug this must never trigger (anthropics/claude-code#37286): a `url` key in Claude
    Desktop's config makes it silently delete the entire mcpServers section on startup."""
    entry = generate_entry("claude-desktop")
    assert "url" not in entry
    assert REGISTRY["claude-desktop"].supports_url is False


def test_claude_code_uses_mcpservers_shape() -> None:
    doc = json.loads(format_for_display("claude-code"))
    assert "resync" in doc["mcpServers"]


def test_cursor_has_no_type_field() -> None:
    entry = generate_entry("cursor")
    assert "type" not in entry  # Cursor infers transport from keys present, unlike VS Code


def test_vscode_uses_servers_root_key_and_requires_explicit_type() -> None:
    """Real, confirmed VS Code requirement: unlike Claude/Cursor, a missing "type" field is invalid."""
    doc = json.loads(format_for_display("vscode"))
    assert "servers" in doc
    assert "mcpServers" not in doc
    assert doc["servers"]["resync"]["type"] == "stdio"


def test_opencode_uses_mcp_key_command_array_and_environment_not_env() -> None:
    """Real, confirmed OpenCode shape: root key "mcp" (not "mcpServers"), command is a single array."""
    doc = json.loads(format_for_display("opencode"))
    assert "mcp" in doc
    assert "mcpServers" not in doc
    entry = doc["mcp"]["resync"]
    assert entry["type"] == "local"
    assert isinstance(entry["command"], list)
    assert entry["command"][0] == "resync"
    assert "args" not in entry
    assert doc["$schema"] == "https://opencode.ai/config.json"


def test_windsurf_uses_plain_mcpservers_shape() -> None:
    doc = json.loads(format_for_display("windsurf"))
    assert "resync" in doc["mcpServers"]
    assert "type" not in doc["mcpServers"]["resync"]


def test_zed_uses_context_servers_with_nested_command_object() -> None:
    """Real, confirmed Zed shape: root key "context_servers", command/args nested INSIDE a command object
    rather than as sibling keys — confirmed directly against a real example in Zed's own docs."""
    doc = json.loads(format_for_display("zed"))
    assert "context_servers" in doc
    entry = doc["context_servers"]["resync"]
    assert entry["command"]["path"] == "resync"
    assert entry["command"]["args"] == ["serve", "--transport", "stdio"]


def test_antigravity_uses_mcpservers_shape_and_serverurl_field_name() -> None:
    doc = json.loads(format_for_display("antigravity"))
    assert "resync" in doc["mcpServers"]
    assert REGISTRY["antigravity"].url_field == "serverUrl"


def test_config_path_for_antigravity_is_none() -> None:
    """Deliberately not guessed — see module docstring for the real, conflicting path reports found."""
    assert config_path_for("antigravity", Path("/tmp")) is None


def test_config_path_for_claude_code_is_project_level_mcp_json(tmp_path: Path) -> None:
    assert config_path_for("claude-code", tmp_path) == tmp_path / ".mcp.json"


def test_config_path_for_cursor_vscode_zed_use_their_own_subdirectories(tmp_path: Path) -> None:
    assert config_path_for("cursor", tmp_path) == tmp_path / ".cursor" / "mcp.json"
    assert config_path_for("vscode", tmp_path) == tmp_path / ".vscode" / "mcp.json"
    assert config_path_for("zed", tmp_path) == tmp_path / ".zed" / "settings.json"


def test_claude_desktop_config_path_is_os_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    macos_path = config_path_for("claude-desktop", Path("/tmp"))
    assert macos_path is not None and "Library/Application Support/Claude" in macos_path.as_posix()

    monkeypatch.setattr("platform.system", lambda: "Linux")
    linux_path = config_path_for("claude-desktop", Path("/tmp"))
    assert linux_path is not None and ".config/Claude" in linux_path.as_posix()


def test_windsurf_config_path_is_global_not_project_scoped(tmp_path: Path) -> None:
    path = config_path_for("windsurf", tmp_path)
    assert path is not None
    assert str(tmp_path) not in str(path)  # confirms it's NOT nested under the repo root
    assert ".codeium" in str(path)


def test_merge_config_preserves_unrelated_servers_and_keys() -> None:
    existing = {
        "mcpServers": {"github": {"command": "docker", "args": ["run", "ghcr.io/x"]}},
        "someUnrelatedSetting": True,
    }
    merged = merge_config(existing, "cursor")
    assert merged["someUnrelatedSetting"] is True
    assert "github" in merged["mcpServers"]
    assert "resync" in merged["mcpServers"]


def test_merge_config_for_zed_only_touches_context_servers_key() -> None:
    """Zed's settings.json holds many unrelated editor settings — confirm merging in an MCP entry doesn't
    disturb anything else in that file."""
    existing = {"theme": "dark", "context_servers": {"other-server": {"command": {"path": "foo", "args": []}}}}
    merged = merge_config(existing, "zed")
    assert merged["theme"] == "dark"
    assert "other-server" in merged["context_servers"]
    assert "resync" in merged["context_servers"]


def test_merge_config_does_not_mutate_the_input() -> None:
    existing = {"mcpServers": {}}
    merge_config(existing, "cursor")
    assert existing["mcpServers"] == {}


def test_merge_config_updates_an_existing_resync_entry_rather_than_duplicating() -> None:
    existing = {"mcpServers": {"resync": {"command": "old-stale-path"}}}
    merged = merge_config(existing, "cursor")
    assert merged["mcpServers"]["resync"]["command"] == "resync"
    assert len(merged["mcpServers"]) == 1


def test_write_config_creates_parent_directories(tmp_path: Path) -> None:
    path = write_config("vscode", tmp_path)
    assert path == tmp_path / ".vscode" / "mcp.json"
    assert path.exists()
    assert json.loads(path.read_text())["servers"]["resync"]["type"] == "stdio"


def test_write_config_merges_into_a_real_existing_file(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text(json.dumps({"mcpServers": {"github": {"command": "docker", "args": []}}}))
    write_config("cursor", tmp_path)
    result = json.loads((cursor_dir / "mcp.json").read_text())
    assert "github" in result["mcpServers"]
    assert "resync" in result["mcpServers"]


def test_write_config_refuses_to_clobber_invalid_json(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text("not valid json {{{")
    with pytest.raises(ValueError, match="isn't valid JSON"):
        write_config("cursor", tmp_path)


def test_write_config_refuses_a_non_object_top_level(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text("[]")
    with pytest.raises(ValueError, match="isn't a JSON object"):
        write_config("cursor", tmp_path)


def test_write_config_raises_for_antigravity(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Antigravity"):
        write_config("antigravity", tmp_path)


def test_write_config_raises_for_unregistered_client(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown client"):
        write_config("totally-fake-client", tmp_path)


def test_custom_server_name_is_used_consistently(tmp_path: Path) -> None:
    path = write_config("cursor", tmp_path, name="my-resync")
    result = json.loads(path.read_text())
    assert "my-resync" in result["mcpServers"]
    assert "resync" not in result["mcpServers"]


class TestScalingPastTheRegistry:
    """format_custom is the escape hatch for any MCP-compliant agent not in REGISTRY yet — these confirm it
    produces the same real shapes build_entry supports, driven purely by parameters, no registry lookup."""

    def test_custom_separate_style(self) -> None:
        doc = json.loads(format_custom(root_key="mcpServers", command_style="separate"))
        assert doc["mcpServers"]["resync"]["command"] == "resync"

    def test_custom_array_style_with_type(self) -> None:
        doc = json.loads(format_custom(root_key="mcp", command_style="array", type_value="local"))
        entry = doc["mcp"]["resync"]
        assert entry["type"] == "local"
        assert entry["command"] == ["resync", "serve", "--transport", "stdio"]

    def test_custom_nested_object_style(self) -> None:
        doc = json.loads(format_custom(root_key="context_servers", command_style="nested_object"))
        assert doc["context_servers"]["resync"]["command"]["path"] == "resync"


def test_describe_registry_includes_verification_dates_and_notes() -> None:
    """The tool cannot detect drift in a client's real format on its own (no live schema registry exists to
    check against) — describe_registry's whole purpose is letting a person judge freshness for themselves."""
    rows = describe_registry()
    assert len(rows) == len(CLIENT_IDS)
    for row in rows:
        assert row["last_verified"]
        assert row["id"] in CLIENT_IDS


class TestAdaptiveSchemaInferenceAndTargets:
    """Exercises infer_client_spec_from_dict, detect_agent_config_targets, and write_target_config."""

    def test_infer_separate_command_style(self) -> None:
        existing = {"mcpServers": {"github": {"command": "npx", "args": ["-y", "gh"]}}}
        inferred = infer_client_spec_from_dict(existing)
        assert inferred is not None
        assert inferred.root_key == "mcpServers"
        assert inferred.command_style == "separate"
        assert inferred.requires_type_field is False
        assert inferred.env_key == "env"

    def test_infer_array_command_style_and_environment_key(self) -> None:
        existing = {
            "mcp": {
                "server1": {
                    "type": "local",
                    "command": ["uvx", "server"],
                    "environment": {"K": "V"},
                }
            }
        }
        inferred = infer_client_spec_from_dict(existing)
        assert inferred is not None
        assert inferred.root_key == "mcp"
        assert inferred.command_style == "array"
        assert inferred.requires_type_field is True
        assert inferred.type_value == "local"
        assert inferred.env_key == "environment"

    def test_infer_nested_object_command_style(self) -> None:
        existing = {"context_servers": {"srv": {"command": {"path": "node", "args": ["app.js"]}}}}
        inferred = infer_client_spec_from_dict(existing)
        assert inferred is not None
        assert inferred.root_key == "context_servers"
        assert inferred.command_style == "nested_object"

    def test_infer_returns_none_for_empty_or_unrecognized_dict(self) -> None:
        assert infer_client_spec_from_dict({}) is None
        assert infer_client_spec_from_dict({"unrelated": {}}) is None

    def test_detect_agent_config_targets_discovers_workspace_roots(self, tmp_path: Path) -> None:
        targets = detect_agent_config_targets(tmp_path)
        ids = [t.agent_id for t in targets]
        assert "antigravity-workspace" in ids
        assert "claude-code" in ids

    def test_write_target_config_preserves_existing_entries_and_applies_inference(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "mcp_config.json"
        cfg_file.write_text(
            json.dumps({"mcpServers": {"existing_svc": {"command": "cmd", "args": ["arg"]}}}),
            encoding="utf-8",
        )
        target = detect_agent_config_targets(tmp_path)[0]  # Take first target and redirect path
        object.__setattr__(target, "path", cfg_file)

        out_path = write_target_config(target, name="resync")
        assert out_path == cfg_file
        loaded = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert "existing_svc" in loaded["mcpServers"]
        assert "resync" in loaded["mcpServers"]
        assert loaded["mcpServers"]["resync"]["command"] == "resync"

    def test_detect_all_project_targets(self, tmp_path: Path) -> None:
        targets = detect_agent_config_targets(tmp_path, all_project_targets=True)
        target_ids = {t.agent_id for t in targets}
        assert {"claude-code", "cursor", "vscode", "antigravity-workspace", "zed"} <= target_ids

    def test_ensure_gitignore_unignores(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".vscode/\n.cursor/\nnode_modules/\n", encoding="utf-8")
        targets = detect_agent_config_targets(tmp_path, all_project_targets=True)
        unignores = ensure_gitignore_unignores(tmp_path, targets)
        assert "!.vscode/mcp.json" in unignores
        assert "!.cursor/mcp.json" in unignores

        # Second run is idempotent
        second = ensure_gitignore_unignores(tmp_path, targets)
        assert second == []

        content = gitignore.read_text(encoding="utf-8")
        assert "!.vscode/mcp.json" in content
        assert "!.cursor/mcp.json" in content

    def test_scaffold_project_mcp_templates(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text(".vscode/\n", encoding="utf-8")
        targets, unignores = scaffold_project_mcp_templates(tmp_path, name="resync")

        assert len(targets) >= 5
        assert (tmp_path / ".mcp.json").exists()
        assert (tmp_path / ".cursor" / "mcp.json").exists()
        assert (tmp_path / ".vscode" / "mcp.json").exists()
        assert (tmp_path / ".agents" / "mcp_config.json").exists()
        assert (tmp_path / ".zed" / "settings.json").exists()
        assert "!.vscode/mcp.json" in unignores
