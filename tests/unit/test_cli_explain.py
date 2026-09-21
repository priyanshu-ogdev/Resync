"""Unit tests for the CLI explain and dashboard commands."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from resync.cli.main import app

runner = CliRunner()


def test_cli_explain_symbol(tmp_path: Path) -> None:
    result = runner.invoke(app, ["explain", "transformers.pipeline", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "Explainability Report" in result.output
    assert "transformers.pipeline" in result.output
    assert "Decomposed Trust Score" in result.output


def test_cli_dashboard_help() -> None:
    result = runner.invoke(app, ["dashboard", "--help"])
    assert result.exit_code == 0
    assert "Launch the interactive Resync Review & Explainability Dashboard" in result.output
    assert "--port" in result.output
    assert "--browser" in result.output


def test_cli_check_explain_flag(tmp_path: Path) -> None:
    # A fresh empty repo should pass with no issues
    result = runner.invoke(app, ["check", str(tmp_path), "--no-provenance", "--explain"])
    assert result.exit_code == 0
    assert "Scanning" in result.output
    assert "No dependency issues" in result.output


def test_cli_sync_explain_flag(tmp_path: Path) -> None:
    result = runner.invoke(app, ["sync", str(tmp_path), "--explain"])
    assert result.exit_code == 0
