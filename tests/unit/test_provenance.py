"""Unit tests for verification/provenance.py's HTTP and outcome-classification logic, using
httpx.MockTransport (see tests/unit/test_verify_package.py's own justification for this approach — proving
this module reacts correctly to each of PyPI's real, already-confirmed response shapes, not re-proving PyPI
itself). Real Sigstore verification (the TUF-trust-root-dependent path) is exercised in
test_provenance_integration.py against real network, where it's honestly expected to hit
CHECK_UNAVAILABLE in this specific sandbox — see that module and provenance.py's own docstring for why.
"""

from __future__ import annotations

import importlib.util

import httpx
import pytest

from resync.verification.provenance import ProvenanceOutcome, check_provenance

# This one test genuinely needs pypi_attestations installed (it exercises Provenance.model_validate's real
# parsing failure mode) — unlike the rest of this file, fixed to no longer need it at all by moving
# provenance.py's import past its early-return paths (see that module's docstring). A targeted skip here,
# not a whole-file one, so the other 6 tests keep running and catching regressions in this sandbox.
_pypi_attestations_spec = importlib.util.find_spec("pypi_attestations")

_SUBJECT_DIGEST = "f045b207f2e12605cf775ec38e89c5eda625d71ffa7830477db65e47ec2bc8b2"


def _release_json(filename: str) -> dict:
    return {"urls": [{"filename": filename, "digests": {"sha256": _SUBJECT_DIGEST}}]}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_no_attestation_reported_as_no_attestation_not_a_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/pypi/" in str(request.url):
            return httpx.Response(200, json=_release_json("six-1.16.0-py2.py3-none-any.whl"))
        return httpx.Response(404)  # PyPI's real Integrity API 404 for a file with no attestation

    result = check_provenance("six", "1.16.0", client=_client(handler))
    assert result.outcome == ProvenanceOutcome.NO_ATTESTATION


def test_release_not_found_reported_as_check_unavailable_not_a_verdict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    result = check_provenance("fake-pkg", "9.9.9", client=_client(handler))
    assert result.outcome == ProvenanceOutcome.CHECK_UNAVAILABLE
    assert "not found on PyPI" in result.files[0].detail


def test_pypi_unreachable_reported_as_check_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = check_provenance("requests", "2.34.2", client=_client(handler))
    assert result.outcome == ProvenanceOutcome.CHECK_UNAVAILABLE


def test_integrity_api_unreachable_after_good_release_response_is_check_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/pypi/" in str(request.url):
            return httpx.Response(200, json=_release_json("pkg-1.0.0-py3-none-any.whl"))
        raise httpx.ConnectError("blocked", request=request)

    result = check_provenance("pkg", "1.0.0", client=_client(handler))
    assert result.outcome == ProvenanceOutcome.CHECK_UNAVAILABLE


def test_multiple_files_report_the_worst_outcome_overall() -> None:
    """One file has no attestation (fine), the other's Integrity API call fails outright (not fine) — the
    aggregate must be CHECK_UNAVAILABLE, not silently averaged away by the clean file."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/pypi/" in url:
            return httpx.Response(
                200,
                json={
                    "urls": [
                        {"filename": "pkg-1.0.0-py3-none-any.whl", "digests": {"sha256": _SUBJECT_DIGEST}},
                        {"filename": "pkg-1.0.0.tar.gz", "digests": {"sha256": _SUBJECT_DIGEST}},
                    ]
                },
            )
        if "pkg-1.0.0-py3-none-any.whl" in url:
            return httpx.Response(404)
        raise httpx.ConnectError("blocked", request=request)

    result = check_provenance("pkg", "1.0.0", client=_client(handler))
    assert result.outcome == ProvenanceOutcome.CHECK_UNAVAILABLE
    outcomes = {f.filename: f.outcome for f in result.files}
    assert outcomes["pkg-1.0.0-py3-none-any.whl"] == ProvenanceOutcome.NO_ATTESTATION
    assert outcomes["pkg-1.0.0.tar.gz"] == ProvenanceOutcome.CHECK_UNAVAILABLE


@pytest.mark.skipif(_pypi_attestations_spec is None, reason="pypi_attestations not installed in this sandbox")
def test_malformed_integrity_response_is_check_unavailable_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/pypi/" in str(request.url):
            return httpx.Response(200, json=_release_json("pkg-1.0.0-py3-none-any.whl"))
        return httpx.Response(200, content=b"not valid json at all {{{")

    result = check_provenance("pkg", "1.0.0", client=_client(handler))
    assert result.outcome == ProvenanceOutcome.CHECK_UNAVAILABLE


def test_no_distribution_files_is_no_attestation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"urls": []})

    result = check_provenance("pkg", "1.0.0", client=_client(handler))
    assert result.outcome == ProvenanceOutcome.NO_ATTESTATION


def test_missing_pypi_attestations_reports_check_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if "pypi_attestations" in name or "sigstore" in name:
            raise ImportError(f"No module named {name}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", mock_import)

    def handler(request: httpx.Request) -> httpx.Response:
        if "/pypi/" in str(request.url):
            return httpx.Response(200, json=_release_json("pkg-1.0.0-py3-none-any.whl"))
        return httpx.Response(200, json={"attestation_bundles": []})

    result = check_provenance("pkg", "1.0.0", client=_client(handler))
    assert result.outcome == ProvenanceOutcome.CHECK_UNAVAILABLE
    assert "not installed" in result.files[0].detail
