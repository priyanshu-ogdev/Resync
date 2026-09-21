from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from resync.server.tools import (
    VerificationOutcome,
    clear_package_cache,
    get_package_cache_stats,
    verify_package,
)

_RealClient = httpx.Client


@pytest.fixture(autouse=True)
def clean_cache() -> None:
    clear_package_cache()
    yield
    clear_package_cache()


def test_verify_package_caches_positive_result(tmp_path: Path) -> None:
    request_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if "pypi.org" in str(request.url):
            return httpx.Response(200, json={"info": {"version": "1.0.0"}})
        if "api.osv.dev" in str(request.url):
            return httpx.Response(200, json={"vulns": []})
        return httpx.Response(404)

    with patch(
        "resync.server.tools.httpx.Client",
        side_effect=lambda **kw: _RealClient(transport=httpx.MockTransport(mock_handler)),
    ):
        res1 = verify_package("demo-pkg", "pypi", tmp_path)
        assert res1.outcome == VerificationOutcome.OK
        assert request_count == 2
        stats1 = get_package_cache_stats()
        assert stats1["misses"] == 1
        assert stats1["hits"] == 0

        # Second call should hit the cache!
        res2 = verify_package("demo-pkg", "pypi", tmp_path)
        assert res2.outcome == VerificationOutcome.OK
        assert request_count == 2  # No new requests!
        stats2 = get_package_cache_stats()
        assert stats2["hits"] == 1


def test_verify_package_cache_is_case_insensitive(tmp_path: Path) -> None:
    request_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if "pypi.org" in str(request.url):
            return httpx.Response(200, json={"info": {"version": "1.0.0"}})
        if "api.osv.dev" in str(request.url):
            return httpx.Response(200, json={"vulns": []})
        return httpx.Response(404)

    with patch(
        "resync.server.tools.httpx.Client",
        side_effect=lambda **kw: _RealClient(transport=httpx.MockTransport(mock_handler)),
    ):
        res1 = verify_package("MyPackage", "PyPI", tmp_path)
        assert res1.outcome == VerificationOutcome.OK
        assert request_count == 2

        res2 = verify_package("mypackage", "pypi", tmp_path)
        assert res2.outcome == VerificationOutcome.OK
        assert request_count == 2
        assert get_package_cache_stats()["hits"] == 1


def test_verify_package_does_not_cache_check_unavailable(tmp_path: Path) -> None:
    request_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise httpx.ConnectError("Network is down", request=request)

    with patch(
        "resync.server.tools.httpx.Client",
        side_effect=lambda **kw: _RealClient(transport=httpx.MockTransport(mock_handler)),
    ):
        res1 = verify_package("flaky-pkg", "pypi", tmp_path)
        assert res1.outcome == VerificationOutcome.CHECK_UNAVAILABLE
        assert request_count == 1

        # Second call should re-check, not return cached unavailable
        res2 = verify_package("flaky-pkg", "pypi", tmp_path)
        assert res2.outcome == VerificationOutcome.CHECK_UNAVAILABLE
        assert request_count == 2
        assert get_package_cache_stats()["hits"] == 0


def test_verify_package_explicit_client_bypasses_cache(tmp_path: Path) -> None:
    request_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if "pypi.org" in str(request.url):
            return httpx.Response(200, json={"info": {"version": "1.0.0"}})
        if "api.osv.dev" in str(request.url):
            return httpx.Response(200, json={"vulns": []})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    res1 = verify_package("test-pkg", "pypi", tmp_path, client=client)
    assert res1.outcome == VerificationOutcome.OK
    assert request_count == 2

    res2 = verify_package("test-pkg", "pypi", tmp_path, client=client)
    assert res2.outcome == VerificationOutcome.OK
    assert request_count == 4  # Client injected -> bypass cache
    assert get_package_cache_stats()["hits"] == 0


def test_verify_package_cache_expires_after_ttl(tmp_path: Path) -> None:
    request_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if "pypi.org" in str(request.url):
            return httpx.Response(200, json={"info": {"version": "1.0.0"}})
        if "api.osv.dev" in str(request.url):
            return httpx.Response(200, json={"vulns": []})
        return httpx.Response(404)

    # Use monkeypatched short TTL
    with (
        patch("resync.server.tools._DEFAULT_CACHE_TTL", 0.05),
        patch(
            "resync.server.tools.httpx.Client",
            side_effect=lambda **kw: _RealClient(transport=httpx.MockTransport(mock_handler)),
        ),
    ):
        verify_package("short-ttl", "pypi", tmp_path)
        assert request_count == 2

        time.sleep(0.1)  # Wait for expiration

        verify_package("short-ttl", "pypi", tmp_path)
        assert request_count == 4  # Expired and re-fetched!
