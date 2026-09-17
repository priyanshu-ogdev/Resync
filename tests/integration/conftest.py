"""Shared fixtures for tests/integration/ — real-network-dependent tests need a genuine reachability check,
not just a "is the tool installed" check.

Found necessary directly, not assumed: `test_resolver_integration.py`, `test_resolve_cli_integration.py`,
and `test_provenance_integration.py` originally guarded only on `shutil.which("uv") is not None` (or nothing
at all) — which correctly detects a missing binary but says nothing about whether the network is actually
reachable. This development environment is exactly the case that distinction matters for: `uv` is installed,
but the network is not — an egress proxy returns a real HTTP 403 for `pypi.org` rather than the connection
simply failing to establish, so a plain `try/except httpx.HTTPError` reachability check isn't sufficient
either (that would only catch a connection failure, not "reachable but blocked"). `_pypi_is_reachable` checks
for an actual `200`, not merely "no exception was raised", specifically to catch this sandbox's real behavior.
"""

from __future__ import annotations

import httpx
import pytest


def _pypi_is_reachable() -> bool:
    try:
        response = httpx.get("https://pypi.org/pypi/pip/json", timeout=5.0)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


requires_network = pytest.mark.skipif(
    not _pypi_is_reachable(), reason="pypi.org is not reachable from this environment (checked, not assumed)"
)
