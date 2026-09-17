"""Integration coverage for `resync check` (cli/main.py), driven through Typer's CliRunner — the real CLI
entry point — against a real, tiny repo directory. Uses only pinned packages/symbols so it needs no live
network (verify_package/check_symbol_exists both short-circuit on a resync.toml pin before any network
call — see server/tools.py), keeping this test fast and independent of network availability, consistent
with tests/unit/test_verify_package.py's own approach.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from resync.cli.main import app


def test_check_reports_no_issues_for_a_fully_pinned_repo(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["legacy-pkg>=1.0"]\n')
    (tmp_path / "resync.toml").write_text(
        '[[pin]]\npackage = "legacy-pkg"\nmax_version = "99.0.0"\nreason = "frozen"\n'
    )
    (tmp_path / "sample.py").write_text("import legacy_pkg\nlegacy_pkg.old_call()\n")

    runner = CliRunner()
    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "No dependency issues" in result.output


def test_check_exits_nonzero_when_a_dependency_is_not_pinned_and_unverifiable(tmp_path: Path) -> None:
    """Without a pin, verify_package has to actually reach PyPI/OSV. Whatever the real outcome is in this
    environment — PACKAGE_NOT_FOUND (this name genuinely isn't a real package) or CHECK_UNAVAILABLE (an
    advisory API blocked by this sandbox's own egress policy) — both are actionable outcomes, and the point
    of this test is that neither is silently swallowed into an exit-0 "no issues" result."""
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["some-unpinned-package>=1.0"]\n')

    runner = CliRunner()
    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert "some-unpinned-package" in result.output
