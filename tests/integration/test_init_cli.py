"""Tests for `resync init` (cli/main.py + cli/init_wizard.py), driven through Typer's CliRunner with
simulated stdin — the same entry point a real terminal invocation goes through, interactive prompts included.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resync.cli.main import app
from resync.knowledge import store

runner = CliRunner()


@pytest.fixture(autouse=True)
def _mock_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file may reach the seeding step, which needs an embedding call — monkeypatched
    globally for this file, matching the established pattern (tests/unit/test_store.py), since a live call
    to download nomic-embed-text-v1.5 isn't reachable from this environment."""
    monkeypatch.setattr(store, "embed_document", lambda text: [0.0] * store.EMBEDDING_DIM)


def test_non_interactive_yes_writes_defaults_with_no_prompts(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    config_path = tmp_path / "resync.toml"
    assert config_path.exists()
    with config_path.open("rb") as f:
        data = tomllib.load(f)
    assert data["project"]["mode"] == "hybrid"
    assert data["project"]["target_profile"] == "pinned"
    assert data["confidence"]["auto_apply_above"] == 0.95
    assert data["pin"] == []


def test_yes_defaults_to_seeding_the_knowledge_store(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert store.default_db_path(tmp_path).exists()


def test_no_seed_flag_skips_seeding_even_under_yes(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--yes", "--no-seed"])
    assert result.exit_code == 0, result.output
    assert not store.default_db_path(tmp_path).exists()


def test_interactive_walkthrough_accepting_every_default(tmp_path: Path) -> None:
    # mode(enter=hybrid), profile(enter=pinned), threshold(enter=0.95), pins?(n), seed now?(n)
    result = runner.invoke(app, ["init", str(tmp_path)], input="\n\n\nn\nn\n")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "resync.toml").exists()
    assert not store.default_db_path(tmp_path).exists()  # answered "n" to seeding


def test_interactive_walkthrough_choosing_non_default_mode(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path)], input="realtime\nlatest\n0.8\nn\nn\n")
    assert result.exit_code == 0, result.output
    with (tmp_path / "resync.toml").open("rb") as f:
        data = tomllib.load(f)
    assert data["project"]["mode"] == "realtime"
    assert data["project"]["target_profile"] == "latest"
    assert data["confidence"]["auto_apply_above"] == 0.8


def test_interactive_walkthrough_adding_pins(tmp_path: Path) -> None:
    # pins? y -> package, max_version, reason, add another? n -> seed now? n
    result = runner.invoke(
        app, ["init", str(tmp_path)], input="\n\n\ny\nrequests\n2.0.0\ntest pin\nn\nn\n"
    )
    assert result.exit_code == 0, result.output
    with (tmp_path / "resync.toml").open("rb") as f:
        data = tomllib.load(f)
    assert len(data["pin"]) == 1
    assert data["pin"][0]["package"] == "requests"
    assert data["pin"][0]["max_version"] == "2.0.0"


def test_interactive_walkthrough_adding_multiple_pins(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["init", str(tmp_path)],
        input="\n\n\ny\nrequests\n2.0.0\nr1\ny\nnumpy\n1.0.0\nn1\nn\nn\n",
    )
    assert result.exit_code == 0, result.output
    with (tmp_path / "resync.toml").open("rb") as f:
        data = tomllib.load(f)
    assert {p["package"] for p in data["pin"]} == {"requests", "numpy"}


def test_existing_config_is_not_overwritten_without_confirmation(tmp_path: Path) -> None:
    (tmp_path / "resync.toml").write_text("# existing config\n")
    result = runner.invoke(app, ["init", str(tmp_path)], input="n\n")  # decline overwrite
    assert result.exit_code == 0
    assert (tmp_path / "resync.toml").read_text() == "# existing config\n"


def test_yes_overwrites_existing_config_without_asking(tmp_path: Path) -> None:
    (tmp_path / "resync.toml").write_text("# existing config\n")
    result = runner.invoke(app, ["init", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert "# existing config" not in (tmp_path / "resync.toml").read_text()


def test_invalid_threshold_input_falls_back_to_default_rather_than_crashing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path)], input="\n\nnot-a-number\nn\nn\n")
    assert result.exit_code == 0, result.output
    with (tmp_path / "resync.toml").open("rb") as f:
        data = tomllib.load(f)
    assert data["confidence"]["auto_apply_above"] == 0.95
