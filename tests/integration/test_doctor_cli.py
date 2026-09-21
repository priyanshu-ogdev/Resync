from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from resync.cli.main import app
from resync.knowledge import store


def _fake_embed(text: str) -> list[float]:
    return [0.0] * store.EMBEDDING_DIM


@pytest.fixture(autouse=True)
def mock_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "embed_document", _fake_embed)


def test_doctor_unconfigured_repo_exits_zero(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["doctor", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "System & Environment Diagnostics" in result.output
    assert "Python Runtime" in result.output
    assert "uv Resolver" in result.output
    assert "ast-grep Binary" in result.output
    assert "resync.toml" in result.output
    assert "Knowledge Store" in result.output
    assert "Project Manifest" in result.output
    assert "Agent Configs" in result.output
    assert "Package Cache" in result.output


def test_doctor_configured_repo_shows_pass(tmp_path: Path) -> None:
    # Set up resync.toml
    (tmp_path / "resync.toml").write_text('[project]\nmode = "hybrid"\n')
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\nversion = "0.1.0"\n')

    # Seed the store
    runner = CliRunner()
    seed_res = runner.invoke(app, ["seed", str(tmp_path)])
    assert seed_res.exit_code == 0

    # Create an agent config for cursor
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    (cursor_dir / "mcp.json").write_text('{"mcpServers": {"resync": {"command": "resync"}}}\n')

    result = runner.invoke(app, ["doctor", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "System & Environment Diagnostics" in result.output
    assert "Valid" in result.output  # resync.toml PASS details
    assert "record(s)" in result.output  # Knowledge Store PASS details
    assert "Cursor" in result.output  # Agent Configs PASS details


def test_doctor_fix_option_interactively_repairs(tmp_path: Path) -> None:
    runner = CliRunner()
    # Provide 'y' for seed prompt and 'y' for scaffold prompt
    result = runner.invoke(app, ["doctor", str(tmp_path), "--fix"], input="y\ny\n")

    assert result.exit_code == 0, result.output
    assert "Seeded" in result.output or "Successfully seeded" in result.output or "Scaffolded" in result.output

    # Check store was seeded
    db_path = store.default_db_path(tmp_path)
    assert db_path.exists()
