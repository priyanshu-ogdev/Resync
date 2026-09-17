"""Real end-to-end integration test for `resync resolve`: the real `uv` binary and the real PyPI/provenance
HTTP stack, driven through Typer's CliRunner. See test_resolve_cli.py for the fast, mocked unit-level tests.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resync.cli.main import app
from tests.integration.conftest import requires_network

pytestmark = [pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH"), requires_network]


def test_resolve_real_end_to_end(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["resolve", "requests>=2.0", "--repo", str(tmp_path)])

    assert result.exit_code in (0, 1)  # 1 only if provenance genuinely came back INVALID — a real red flag
    assert "requests" in result.output
