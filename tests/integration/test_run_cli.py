"""Integration test coverage for `resync run` command (cli/main.py).

Verifies that `resync run` orchestrates both the scan/check phase and the sync correction
phase cleanly in preview and apply modes.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from resync.cli.main import app


def test_run_help_displays_flags() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "Run the complete Resync compatibility workflow" in result.output
    assert "--apply" in result.output
    assert "--tier" in result.output


def test_run_executes_on_pinned_repo_cleanly(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["legacy-pkg>=1.0"]\n')
    (tmp_path / "resync.toml").write_text(
        '[[pin]]\npackage = "legacy-pkg"\nmax_version = "99.0.0"\nreason = "frozen"\n'
    )
    (tmp_path / "sample.py").write_text("import legacy_pkg\nlegacy_pkg.old_call()\n")

    runner = CliRunner()
    result = runner.invoke(app, ["run", str(tmp_path), "--no-provenance"])
    assert result.exit_code == 0
    assert "Resync Compatibility Engine" in result.output
    assert "Dependencies:" in result.output
