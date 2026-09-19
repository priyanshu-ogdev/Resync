"""Unit tests for `resync resolve` (cli/main.py), mocked at the resolve/provenance module boundary for
speed and determinism — see test_resolve_cli_integration.py for the real end-to-end version."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from resync.adapters.python.resolver import ResolvedDependency, ResolverError, ResolveResult, ResolverUnavailableError
from resync.cli.main import app
from resync.verification.provenance import FileProvenanceResult, ProvenanceOutcome, ProvenanceResult


def _fake_provenance(package: str, version: str, outcome: ProvenanceOutcome) -> ProvenanceResult:
    return ProvenanceResult(
        package=package,
        version=version,
        outcome=outcome,
        files=[FileProvenanceResult(filename=f"{package}-{version}.whl", outcome=outcome, detail="test")],
    )


def test_resolve_reports_verified_packages_and_exits_zero(tmp_path: Path) -> None:
    fake_result = ResolveResult(dependencies=[ResolvedDependency(name="requests", version="2.34.2")], pylock_toml="")
    with (
        patch("resync.adapters.python.resolver.resolve", return_value=fake_result),
        patch(
            "resync.verification.provenance.check_provenance",
            return_value=_fake_provenance("requests", "2.34.2", ProvenanceOutcome.VERIFIED),
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(app, ["resolve", "requests>=2.0", "--repo", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "requests" in result.output
    assert "verified" in result.output


def test_resolve_exits_nonzero_and_warns_on_invalid_provenance(tmp_path: Path) -> None:
    fake_result = ResolveResult(
        dependencies=[ResolvedDependency(name="suspicious-pkg", version="1.0.0")], pylock_toml=""
    )
    with (
        patch("resync.adapters.python.resolver.resolve", return_value=fake_result),
        patch(
            "resync.verification.provenance.check_provenance",
            return_value=_fake_provenance("suspicious-pkg", "1.0.0", ProvenanceOutcome.INVALID),
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(app, ["resolve", "suspicious-pkg", "--repo", str(tmp_path)])

    assert result.exit_code == 1
    assert "failed provenance verification" in result.output.lower()


def test_resolve_exits_2_when_resolver_unavailable(tmp_path: Path) -> None:
    with patch("resync.adapters.python.resolver.resolve", side_effect=ResolverUnavailableError("network down")):
        runner = CliRunner()
        result = runner.invoke(app, ["resolve", "requests", "--repo", str(tmp_path)])

    assert result.exit_code == 2
    assert "unavailable" in result.output.lower()


def test_resolve_exits_1_on_genuine_resolver_error(tmp_path: Path) -> None:
    with patch("resync.adapters.python.resolver.resolve", side_effect=ResolverError("no solution found")):
        runner = CliRunner()
        result = runner.invoke(app, ["resolve", "fake-pkg-xyz", "--repo", str(tmp_path)])

    assert result.exit_code == 1
    assert "resolution failed" in result.output.lower()
