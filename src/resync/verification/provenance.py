"""Supply-chain provenance gate — docs/architecture.md#supply-chain-provenance-gate: "before landing any
resolved version, check it against OSV.dev and the GitHub Advisory Database, and where available its
Sigstore signature or SLSA provenance attestation." OSV/GHSA are already covered by `verify_package`
(server/tools.py); this module is the "where available, Sigstore" half, called on a version the resolver
(resolve/resolver.py) has just picked, before it's allowed to land.

Built on `pypi_attestations` (PyPA's own purpose-built PEP 740 attestation library), not raw `sigstore` —
matches this project's "reuse a purpose-built tool" stance elsewhere (see docs/multi-language-adapters.md's
framing note). Verified against PyPI's real Integrity API
(`https://pypi.org/integrity/{project}/{version}/{filename}/provenance`) and the real installed
`pypi-attestations`/`sigstore` packages' actual return shapes — not assumed from either library's docs.

**A real, sandbox-specific gap found while building this, not glossed over**: `pypi_attestations.Attestation.
verify()` needs `sigstore`'s TUF trust-root, fetched from `tuf-repo-cdn.sigstore.dev` on first use. That host
is not on this development environment's network allowlist (confirmed via a live request: `x-deny-reason:
host_not_allowed`) — the exact same class of gap as `api.osv.dev` being blocked for `verify_package`. Handled
the same way: a distinct `ProvenanceOutcome.CHECK_UNAVAILABLE`, never silently reported as verified. A real
deployment with normal network access reaches this host fine; this is this sandbox's own restriction, not a
design gap (see CHANGELOG.md for the parallel OSV.dev note).

**What "verified" means here, precisely** — worth stating explicitly since it's easy to overclaim: a
`VERIFIED` result means the artifact was cryptographically confirmed to have been built and published by the
specific CI workflow/repository the attestation bundle itself declares (chain of trust to Sigstore's root,
Rekor transparency-log inclusion, and a signature over the exact artifact digest all check out). It does
**not** mean Resync independently vouches that the declared repository is legitimate or trustworthy — e.g. a
convincingly-named but unrelated repo could still publish a genuinely-signed, genuinely-attested malicious
package. That judgment belongs to whoever reviews the reported publisher identity (surfaced in `detail`),
the same way a TLS certificate proves who's on the other end of a connection without vouching for their
intentions.

**Lazy-imported, matching this project's established convention for optional `server`-extra dependencies**
(`knowledge/extract_api_diff.py`'s `import griffe`, `verification/sandbox.py`'s `import sandbox_runtime`):
`pypi_attestations`/`sigstore.errors` are imported inside the functions that use them, not at module level,
so this module — and anything that merely imports it without calling `check_provenance` — stays importable
in an environment that hasn't run `uv sync --extra server`. Found necessary the same way as those other two
modules: a first draft imported at module level, which broke test collection for any test file importing
this module in an environment without the package installed, precisely the failure mode the lazy-import
convention exists to prevent.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel

if TYPE_CHECKING:
    from pypi_attestations import Publisher

_PYPI_JSON_BASE = "https://pypi.org/pypi"
_PYPI_INTEGRITY_BASE = "https://pypi.org/integrity"


class ProvenanceOutcome(StrEnum):
    VERIFIED = "verified"  # attestation present, cryptographically confirmed against its declared publisher
    NO_ATTESTATION = "no_attestation"  # no PEP 740 attestation published — common, not itself a red flag
    INVALID = "invalid"  # attestation present but failed verification — a real, actionable red flag
    CHECK_UNAVAILABLE = "check_unavailable"  # couldn't complete the check — never treated as a verdict


class FileProvenanceResult(BaseModel):
    filename: str
    outcome: ProvenanceOutcome
    detail: str


class ProvenanceResult(BaseModel):
    """Structured result for one package version, aggregated across every distribution file it published.

    `outcome` is the single worst outcome across `files` (INVALID beats CHECK_UNAVAILABLE beats
    NO_ATTESTATION beats VERIFIED) — a version isn't safe to call "verified" if even one of its published
    files failed verification or couldn't be checked, even if others passed.
    """

    package: str
    version: str
    outcome: ProvenanceOutcome
    files: list[FileProvenanceResult]


_SEVERITY = {
    ProvenanceOutcome.INVALID: 3,
    ProvenanceOutcome.CHECK_UNAVAILABLE: 2,
    ProvenanceOutcome.NO_ATTESTATION: 1,
    ProvenanceOutcome.VERIFIED: 0,
}


def _check_one_file(
    client: httpx.Client, package: str, version: str, filename: str, digest: str
) -> FileProvenanceResult:
    try:
        response = client.get(f"{_PYPI_INTEGRITY_BASE}/{package}/{version}/{filename}/provenance")
    except httpx.HTTPError as exc:
        return FileProvenanceResult(
            filename=filename,
            outcome=ProvenanceOutcome.CHECK_UNAVAILABLE,
            detail=f"could not reach PyPI's Integrity API: {exc}",
        )

    if response.status_code == 404:
        return FileProvenanceResult(
            filename=filename,
            outcome=ProvenanceOutcome.NO_ATTESTATION,
            detail=f"{filename} has no published PEP 740 attestation (common — most PyPI packages don't "
            "publish via Trusted Publishing yet; this is not itself a finding).",
        )

    # Deferred to exactly here, not the top of the function: everything above (a transport failure, or the
    # common "no attestation published at all" case) needs none of pypi_attestations/sigstore, and this
    # project's tests for those two paths should not need the `server` extra installed just to exercise
    # logic that never actually touches it — found necessary directly, not assumed, when those tests failed
    # to collect with the import at the top of the function instead.
    from pypi_attestations import AttestationError, Distribution, Provenance, VerificationError
    from sigstore.errors import Error as SigstoreError

    try:
        response.raise_for_status()
        provenance = Provenance.model_validate(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        return FileProvenanceResult(
            filename=filename,
            outcome=ProvenanceOutcome.CHECK_UNAVAILABLE,
            detail=f"PyPI's Integrity API returned an unexpected response for {filename}: {exc}",
        )

    dist = Distribution(name=filename, digest=digest)
    for bundle in provenance.attestation_bundles:
        for attestation in bundle.attestations:
            try:
                attestation.verify(bundle.publisher, dist)
            except SigstoreError as exc:
                # The TUF trust-root fetch (or any other Sigstore-internal transport failure) is an
                # availability problem, not evidence the attestation is fake — see module docstring.
                return FileProvenanceResult(
                    filename=filename,
                    outcome=ProvenanceOutcome.CHECK_UNAVAILABLE,
                    detail=f"Sigstore verification infrastructure was unreachable for {filename}: {exc}",
                )
            except (VerificationError, AttestationError) as exc:
                return FileProvenanceResult(
                    filename=filename,
                    outcome=ProvenanceOutcome.INVALID,
                    detail=f"{filename}'s attestation failed verification: {exc}",
                )
    publisher_description = (
        _describe_publisher(provenance.attestation_bundles[0].publisher) if provenance.attestation_bundles else None
    )
    return FileProvenanceResult(
        filename=filename,
        outcome=ProvenanceOutcome.VERIFIED,
        detail=f"{filename}: verified as published by {publisher_description}"
        if publisher_description
        else f"{filename}: attestation bundle present but empty (no attestations to verify)",
    )


def _describe_publisher(publisher: Publisher) -> str:
    """Human-readable identity for whichever of PEP 740's four real publisher kinds signed this attestation
    (confirmed live: `GitHubPublisher`/`GitLabPublisher` expose `.repository`, but `GooglePublisher` only has
    `.email` and `CircleCIPublisher` only has `.project_id`/`.vcs_origin` — a real mypy error caught this
    when the code assumed every publisher has `.repository`, which only two of the four actually do)."""
    repository = getattr(publisher, "repository", None)
    if repository is not None:
        return str(repository)
    email = getattr(publisher, "email", None)
    if email is not None:
        return f"Google-published ({email})"
    vcs_origin = getattr(publisher, "vcs_origin", None)
    if vcs_origin is not None:
        return str(vcs_origin)
    return f"{type(publisher).__name__} publisher"


def check_provenance(package: str, version: str, *, client: httpx.Client | None = None) -> ProvenanceResult:
    """Checks every distribution file PyPI has for `package==version` against its own PEP 740 attestation,
    if any. Never raises for "no attestation" or "couldn't check" — both are reported outcomes, per this
    project's `CHECK_UNAVAILABLE` precedent in server/tools.py's `verify_package`; only a genuinely malformed
    call (e.g. an httpx client the caller already closed) would raise.
    """
    owns_client = client is None
    http_client = client or httpx.Client(timeout=15.0)
    try:
        try:
            release_response = http_client.get(f"{_PYPI_JSON_BASE}/{package}/{version}/json")
        except httpx.HTTPError as exc:
            return ProvenanceResult(
                package=package,
                version=version,
                outcome=ProvenanceOutcome.CHECK_UNAVAILABLE,
                files=[
                    FileProvenanceResult(
                        filename="*", outcome=ProvenanceOutcome.CHECK_UNAVAILABLE, detail=f"PyPI unreachable: {exc}"
                    )
                ],
            )
        if release_response.status_code == 404:
            return ProvenanceResult(
                package=package,
                version=version,
                outcome=ProvenanceOutcome.CHECK_UNAVAILABLE,
                files=[
                    FileProvenanceResult(
                        filename="*",
                        outcome=ProvenanceOutcome.CHECK_UNAVAILABLE,
                        detail=f"{package}=={version} not found on PyPI — nothing to check provenance for "
                        "(a real not-found finding belongs to verify_package, not this gate).",
                    )
                ],
            )
        # A real, previously-undiscovered bug caught by this project's own integration test suite: this
        # call was, until now, outside any try/except entirely. Any non-404 HTTP error status (403, 500,
        # 429 — confirmed live: this development sandbox's egress proxy returns 403 for a blocked request,
        # not a connection failure) raised httpx.HTTPStatusError unhandled, crashing check_provenance
        # outright instead of reporting the graceful CHECK_UNAVAILABLE this whole function exists to return
        # for exactly this class of problem. Now caught alongside the malformed-JSON case below, since both
        # are "PyPI responded, but not usably" — the same outcome this project already uses elsewhere.
        try:
            release_response.raise_for_status()
            release_data = release_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return ProvenanceResult(
                package=package,
                version=version,
                outcome=ProvenanceOutcome.CHECK_UNAVAILABLE,
                files=[
                    FileProvenanceResult(
                        filename="*",
                        outcome=ProvenanceOutcome.CHECK_UNAVAILABLE,
                        detail=f"PyPI's JSON API returned an unusable response for {package}=={version}: {exc}",
                    )
                ],
            )

        files = [
            _check_one_file(http_client, package, version, f["filename"], f["digests"]["sha256"])
            for f in release_data.get("urls", [])
        ]
        if not files:
            files = [
                FileProvenanceResult(
                    filename="*",
                    outcome=ProvenanceOutcome.NO_ATTESTATION,
                    detail=f"{package}=={version} has no published distribution files to check.",
                )
            ]
        overall = max((f.outcome for f in files), key=lambda o: _SEVERITY[o])
        return ProvenanceResult(package=package, version=version, outcome=overall, files=files)
    finally:
        if owns_client:
            http_client.close()
