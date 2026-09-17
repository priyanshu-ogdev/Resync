"""Integration coverage for resolve/resolver.py against the real, installed `uv` binary — real network
required (skips cleanly if `uv` isn't on PATH, matching this project's own network-dependent-test convention
in tests/integration/test_extract_api_diff.py). Unit-level classification/parsing logic is already covered
by tests/unit/test_resolver.py's mocked-subprocess tests; what's uniquely proven here is that the real
command line this module builds is actually well-formed uv accepts it, not just that resolver.py reacts
correctly to canned exit codes/output.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from resync.resolve.resolver import ResolvedDependency, ResolverError, resolve
from tests.integration.conftest import requires_network

pytestmark = [pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH"), requires_network]


def test_resolve_against_the_real_uv_binary(tmp_path: Path) -> None:
    result = resolve(["requests>=2.0"], tmp_path)
    names = {d.name for d in result.dependencies}
    assert "requests" in names
    assert all(isinstance(d, ResolvedDependency) and d.version for d in result.dependencies)


def test_resolve_honors_a_real_pin_against_the_real_binary(tmp_path: Path) -> None:
    (tmp_path / "resync.toml").write_text(
        '[[pin]]\npackage = "urllib3"\nmax_version = "1.26.20"\nreason = "test pin"\n'
    )
    result = resolve(["requests>=2.0"], tmp_path)
    urllib3 = next(d for d in result.dependencies if d.name == "urllib3")
    assert urllib3.version == "1.26.20"


def test_resolve_raises_resolver_error_for_a_real_nonexistent_package(tmp_path: Path) -> None:
    with pytest.raises(ResolverError):
        resolve(["definitely-not-a-real-package-xyz123abc"], tmp_path)
