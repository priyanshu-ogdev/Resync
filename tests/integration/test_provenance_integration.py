"""Integration coverage for verification/provenance.py against real PyPI (both the classic JSON API and the
real Integrity API) and the real `pypi_attestations`/`sigstore` verification stack.

Skips as a whole file when PyPI itself isn't reachable (`tests/integration/conftest.py`'s `requires_network`)
— found necessary by actually running these, not assumed: this development environment's egress proxy
returns a real HTTP 403 for every `pypi.org` request, not just for Sigstore's separate
`tuf-repo-cdn.sigstore.dev` trust-root host. The original version of this file assumed only the
Sigstore-specific host was blocked (a narrower, partial-block scenario) and left one test asserting either
`VERIFIED` or `CHECK_UNAVAILABLE` to tolerate exactly that case — a reasonable design for a partial block,
but insufficient once it turned out PyPI itself is unreachable here too, since the other two tests need a
genuine 404 or a genuine 200-with-no-attestation response to assert anything meaningful. Skipping the whole
file is more honest than loosening every assertion to tolerate a total network outage — a real deployment
with normal internet access exercises all three for real.
"""

from __future__ import annotations

from resync.verification.provenance import ProvenanceOutcome, check_provenance
from tests.integration.conftest import requires_network

pytestmark = requires_network


def test_check_provenance_against_a_real_attested_package() -> None:
    """sigstore-python's own PyPI releases carry real PEP 740 attestations (published via GitHub Actions
    Trusted Publishing) — a genuine, real-world attested package, not a synthetic fixture."""
    result = check_provenance("sigstore", "4.5.0")
    assert result.outcome in (ProvenanceOutcome.VERIFIED, ProvenanceOutcome.CHECK_UNAVAILABLE)
    if result.outcome == ProvenanceOutcome.CHECK_UNAVAILABLE:
        assert any("TUF" in f.detail or "Sigstore" in f.detail for f in result.files)


def test_check_provenance_against_a_real_unattested_package() -> None:
    """`six` predates PyPI Trusted Publishing attestations entirely — real package, real "no attestation"
    case, no mocking needed since this doesn't touch the Sigstore/TUF path at all."""
    result = check_provenance("six", "1.16.0")
    assert result.outcome == ProvenanceOutcome.NO_ATTESTATION


def test_check_provenance_against_a_real_nonexistent_release() -> None:
    result = check_provenance("requests", "999.999.999")
    assert result.outcome == ProvenanceOutcome.CHECK_UNAVAILABLE
    assert "not found" in result.files[0].detail
