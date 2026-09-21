"""Unit tests for server/tools.py's verify_package.

Uses httpx.MockTransport (httpx's own first-class testing mechanism — see module docstring in tools.py for
why this counts as real evidence and what it doesn't prove) rather than hitting the live network, which
isn't reachable from this environment anyway.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from resync.server.tools import VerificationOutcome, verify_package


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_pinned_package_short_circuits_before_any_network_call(tmp_path: Path) -> None:
    (tmp_path / "resync.toml").write_text('[[pin]]\npackage = "legacy-pkg"\nmax_version = "1.0.0"\nreason = "frozen"\n')

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no network call should happen for a pinned package")

    result = verify_package("legacy-pkg", "pypi", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.PINNED


def test_existing_clean_package_returns_ok(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/pypi/requests/json":
            return httpx.Response(200, json={"info": {"version": "2.32.3"}})
        assert str(request.url) == "https://api.osv.dev/v1/query"
        assert request.method == "POST"
        return httpx.Response(200, json={"vulns": []})

    result = verify_package("requests", "pypi", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.OK
    assert "2.32.3" in result.detail


def test_nonexistent_package_returns_package_not_found(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    result = verify_package("definitely-not-a-real-package-xyz", "pypi", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.PACKAGE_NOT_FOUND


def test_package_with_advisories_returns_advisory_flagged_with_ids_listed(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "pypi.org" in str(request.url):
            return httpx.Response(200, json={"info": {"version": "1.0.0"}})
        return httpx.Response(200, json={"vulns": [{"id": "GHSA-xxxx"}, {"id": "CVE-2024-0001"}]})

    result = verify_package("vulnerable-pkg", "pypi", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.ADVISORY_FLAGGED
    assert "GHSA-xxxx" in result.detail
    assert "CVE-2024-0001" in result.detail


def test_advisory_list_is_truncated_with_a_count_for_more_than_five(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "pypi.org" in str(request.url):
            return httpx.Response(200, json={"info": {"version": "1.0.0"}})
        return httpx.Response(200, json={"vulns": [{"id": f"CVE-{i}"} for i in range(8)]})

    result = verify_package("very-vulnerable-pkg", "pypi", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.ADVISORY_FLAGGED
    assert "+3 more" in result.detail


def test_unsupported_ecosystem_reports_no_check_performed_rather_than_a_false_ok(tmp_path: Path) -> None:
    """A silent OK for an ecosystem this project doesn't actually check yet would be a falsely-reassuring
    result — must say plainly that nothing was checked, not claim confirmed-clean. Fixed: the outcome is
    now CHECK_UNAVAILABLE (not OK), which is the correct fail-closed value for 'no verdict reached.'"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no network call should happen for an unsupported ecosystem")

    result = verify_package("some-package", "unknown-ecosystem", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.CHECK_UNAVAILABLE
    assert "not yet checked" in result.detail


def test_osv_supported_ecosystem_clean_returns_ok(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.osv.dev" in str(request.url)
        return httpx.Response(200, json={"vulns": []})

    result = verify_package("serde", "crates", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.OK
    assert "no known advisories in OSV.dev" in result.detail


def test_osv_supported_ecosystem_flagged_returns_advisory(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.osv.dev" in str(request.url)
        return httpx.Response(200, json={"vulns": [{"id": "RUSTSEC-2020-0071"}]})

    result = verify_package("smallvec", "crates", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.ADVISORY_FLAGGED
    assert "RUSTSEC-2020-0071" in result.detail


def test_npm_package_clean_returns_ok(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "registry.npmjs.org/react/latest" in str(request.url):
            return httpx.Response(200, json={"version": "19.0.0"})
        assert "api.osv.dev" in str(request.url)
        return httpx.Response(200, json={"vulns": []})

    result = verify_package("react", "npm", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.OK
    assert "react exists on npm" in result.detail
    assert "19.0.0" in result.detail


def test_npm_package_not_found(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    result = verify_package("nonexistent-npm-pkg", "npm", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.PACKAGE_NOT_FOUND
    assert "not found on npm registry" in result.detail


def test_client_is_closed_when_not_injected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the caller doesn't inject a client, verify_package must own and close the one it creates —
    otherwise every call leaks a connection."""
    closed = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if "pypi.org" in str(request.url):
            return httpx.Response(200, json={"info": {"version": "1.0.0"}})
        return httpx.Response(200, json={"vulns": []})

    real_close = httpx.Client.close

    def tracking_close(self: httpx.Client) -> None:
        closed["value"] = True
        real_close(self)

    monkeypatch.setattr(httpx.Client, "close", tracking_close)
    real_client_cls = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client_cls(transport=httpx.MockTransport(handler)))
    verify_package("requests", "pypi", tmp_path)
    assert closed["value"] is True


def test_pypi_unreachable_reports_check_unavailable_not_a_crash_or_false_ok(tmp_path: Path) -> None:
    """A transport-level failure reaching PyPI (network down, DNS failure, proxy block — the exact shape of
    this sandbox's own egress policy blocking a host it doesn't allowlist) must surface as a reported,
    structured finding, not an unhandled exception, and must never be reported as OK — a network failure is
    not evidence the package is clean."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = verify_package("requests", "pypi", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.CHECK_UNAVAILABLE
    assert "PyPI" in result.detail


def test_osv_unreachable_after_good_pypi_response_reports_check_unavailable(tmp_path: Path) -> None:
    """PyPI answers fine (the package genuinely exists) but the advisory check fails — e.g. `api.osv.dev`
    blocked by an egress policy that doesn't allowlist it, a real failure mode hit in this project's own dev
    sandbox, not a hypothetical. Must not silently fall back to reporting the package as OK with no advisory
    check having actually run."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "pypi.org" in str(request.url):
            return httpx.Response(200, json={"info": {"version": "2.32.3"}})
        raise httpx.ConnectError("blocked by egress policy", request=request)

    result = verify_package("requests", "pypi", tmp_path, client=_client(handler))
    assert result.outcome == VerificationOutcome.CHECK_UNAVAILABLE
    assert "OSV" in result.detail
