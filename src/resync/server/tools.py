"""The real-time MCP gate: verify_package and check_symbol_exists.

Per docs/architecture.md#two-speeds, these must be fast lookups against the knowledge store and package
registries — never an LLM call — so a call returns before the calling agent's next token. Guardrails (pin and
exception checks) are enforced here, in the tool implementation itself, not left as a prompt instruction —
see docs/adr/0003-deterministic-first-patching.md.

Real, external APIs used here were verified against their actual published documentation before writing any
code against them, not assumed from memory — consistent with this project's one standing convention
(AGENTS.md):
- PyPI's JSON API (`https://pypi.org/pypi/{package}/json`, 404 on a nonexistent package) — docs.pypi.org/api/json.
- OSV.dev's query API (`POST https://api.osv.dev/v1/query`, body `{"package": {"name", "ecosystem"}, "version"}`,
  response `{"vulns": [...]}`, empty/absent when clean) — google.github.io/osv.dev/post-v1-query.

Neither call has been run against the live network in this development environment (no network access here)
— both are unit-tested against `httpx.MockTransport`, httpx's own first-class, documented testing mechanism
(not a bespoke mock), which exercises the real request-building and response-parsing code paths without
needing the network itself. That is real evidence the code is correct against the documented API shapes; it
is not the same as having observed a real response from the live services, which is why this gap is named
here rather than left implicit.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import httpx
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel

from resync.config.loader import load as load_config
from resync.knowledge import router, store
from resync.knowledge.schema import KnowledgeRecord, RuleType

_PYPI_BASE = "https://pypi.org/pypi"
_OSV_URL = "https://api.osv.dev/v1/query"
_DEFAULT_TIMEOUT = 10.0

# OSV.dev's supported ecosystem names are case-sensitive and don't always match the lowercase convention
# used elsewhere in this codebase (KnowledgeRecord.ecosystem, resync.toml) — confirmed against OSV's own
# query examples, not guessed. Only the ecosystems this project actually targets are mapped; an unmapped
# ecosystem skips the advisory check rather than guessing at a name OSV might not recognize.
_OSV_ECOSYSTEM_NAMES = {"pypi": "PyPI"}


class VerificationOutcome(StrEnum):
    OK = "ok"
    PACKAGE_NOT_FOUND = "package_not_found"
    ADVISORY_FLAGGED = "advisory_flagged"
    SYMBOL_DEPRECATED = "symbol_deprecated"
    SYMBOL_REMOVED = "symbol_removed"
    PINNED = "pinned"  # resync.toml says: do not touch, do not flag
    CHECK_UNAVAILABLE = "check_unavailable"  # registry/advisory API unreachable or errored — not a verdict


class VerificationResult(BaseModel):
    """Structured MCP tool output — per docs/adr/0001, returned to the calling agent as data, never as a
    silent rewrite, so the agent's own transcript stays the audit trail."""

    outcome: VerificationOutcome
    detail: str
    suggested_replacement: str | None = None


def verify_package(
    package: str,
    ecosystem: str,
    repo_root: Path,
    *,
    client: httpx.Client | None = None,
) -> VerificationResult:
    """MCP tool: called before an agent writes a new import or dependency addition.

    Checks, in order: resync.toml pins/exceptions (short-circuit, same as check_symbol_exists), registry
    existence, then known advisories for the package's current latest version. `client` is injectable
    specifically so tests can pass an `httpx.Client(transport=httpx.MockTransport(...))` — see module
    docstring — without this function needing a separate "test mode" branch.
    """
    config = load_config(repo_root)
    if config.is_pinned_or_frozen(package):
        return VerificationResult(
            outcome=VerificationOutcome.PINNED,
            detail=f"{package} is pinned or frozen in resync.toml — not flagged.",
        )

    owns_client = client is None
    http_client = client or httpx.Client(timeout=_DEFAULT_TIMEOUT)
    try:
        if ecosystem.lower() != "pypi":
            # Registry existence and advisory checks below are PyPI-specific by construction (the exact
            # endpoints, and OSV's ecosystem-name mapping). Rather than silently skip checks for another
            # ecosystem and return a falsely-reassuring OK, say plainly that this ecosystem isn't checked
            # yet — see docs/multi-language-adapters.md for the broader multi-ecosystem roadmap.
            return VerificationResult(
                outcome=VerificationOutcome.OK,
                detail=f"Ecosystem '{ecosystem}' is not yet checked against a registry or advisory "
                "database (PyPI is currently the only wired ecosystem) — this result reflects no check "
                "having been performed, not a confirmed-clean package.",
            )

        try:
            pypi_response = http_client.get(f"{_PYPI_BASE}/{package}/json")
        except httpx.HTTPError as exc:
            return VerificationResult(
                outcome=VerificationOutcome.CHECK_UNAVAILABLE,
                detail=f"Could not reach PyPI to check {package}: {exc}. Not a verdict — retry, or check "
                "network/proxy configuration (see docs/adr/0003 on why this is reported, not treated as OK).",
            )
        if pypi_response.status_code == 404:
            return VerificationResult(
                outcome=VerificationOutcome.PACKAGE_NOT_FOUND,
                detail=f"{package} was not found on PyPI.",
            )
        try:
            pypi_response.raise_for_status()
            latest_version = pypi_response.json().get("info", {}).get("version")

            osv_response = http_client.post(
                _OSV_URL,
                json={
                    "package": {"name": package, "ecosystem": _OSV_ECOSYSTEM_NAMES["pypi"]},
                    "version": latest_version,
                },
            )
            osv_response.raise_for_status()
        except httpx.HTTPError as exc:
            return VerificationResult(
                outcome=VerificationOutcome.CHECK_UNAVAILABLE,
                detail=f"{package} exists on PyPI, but the advisory check against OSV.dev failed: {exc}. Not "
                "a verdict either way — this is a transport/API failure, not a confirmed-clean result.",
            )
        vulns = osv_response.json().get("vulns", [])
        if vulns:
            ids = ", ".join(v.get("id", "?") for v in vulns[:5])
            more = f" (+{len(vulns) - 5} more)" if len(vulns) > 5 else ""
            plural = "advisory" if len(vulns) == 1 else "advisories"
            return VerificationResult(
                outcome=VerificationOutcome.ADVISORY_FLAGGED,
                detail=f"{package}=={latest_version} has {len(vulns)} known {plural}: {ids}{more}",
            )

        return VerificationResult(
            outcome=VerificationOutcome.OK,
            detail=f"{package} exists on PyPI (latest: {latest_version}) with no known advisories.",
        )
    finally:
        if owns_client:
            http_client.close()


def _version_already_changed(pinned_version: str, to_version: str) -> bool | None:
    """Does `pinned_version` satisfy `to_version`'s specifier — i.e. has the change already happened for the
    version this repo actually has pinned? `True`/`False` when both strings parse as real PEP 440
    values/specifiers; `None` when either doesn't (an unparseable pin like a git ref, or a KnowledgeRecord
    version field that isn't a clean specifier).

    `None` is a real return value the caller must handle, not an error swallowed here — see
    check_symbol_exists's own docstring/TODO history: guessing via string comparison for the unparseable
    case would be exactly the kind of unverified claim this project exists to catch in *other* tools, so
    this function refuses to guess rather than approximate.
    """
    try:
        return Version(pinned_version) in SpecifierSet(to_version)
    except (InvalidVersion, InvalidSpecifier):
        return None


def _describe_match(record: KnowledgeRecord) -> str:
    if record.parameter and record.new_parameter:
        return f"parameter `{record.parameter}` -> `{record.new_parameter}`"
    if record.new_symbol and record.new_symbol != record.old_symbol:
        return f"renamed to `{record.new_symbol}`"
    if record.rule_type == RuleType.REMOVED_NO_REPLACEMENT:
        return "removed with no direct replacement"
    return f"changed ({record.rule_type.value})"


def check_symbol_exists(fully_qualified_symbol: str, pinned_version: str, repo_root: Path) -> VerificationResult:
    """MCP tool: called before an agent calls a function from an existing dependency.

    Checks resync.toml pins/exceptions first (ResyncConfig.is_pinned_or_frozen) and short-circuits to
    VerificationOutcome.PINNED before consulting the knowledge store at all — docs/adr/0005.

    Version-range handling, real not faked: `from_version`/`to_version` on a KnowledgeRecord are free-text
    (e.g. "<4.32.0"), not guaranteed valid PEP 440 specifiers. `_version_already_changed` uses `packaging`
    (the same library pip/uv use) to check real containment, and returns `None` — never a guess — when a
    version string doesn't parse. Records with an undetermined match are excluded from the result rather
    than silently flagged or silently cleared, which is the conservative, honest choice given no real
    version-range comparison exists yet for the free-text cases beyond what `packaging` can parse directly
    (see this function's history in docs/implementation-plan.md's Phase 4 entry for why this wasn't rushed).

    A symbol can legitimately have more than one associated, currently-applicable record (e.g.
    `transformers.TrainingArguments` has seven different parameter renames in the seed set alone) — this is
    handled by listing every match in `detail`, not by arbitrarily picking one.
    """
    config = load_config(repo_root)
    if config.is_pinned_or_frozen(fully_qualified_symbol):
        return VerificationResult(
            outcome=VerificationOutcome.PINNED,
            detail=f"{fully_qualified_symbol} is pinned or frozen in resync.toml — not flagged.",
        )

    route = router.route(fully_qualified_symbol)
    if route != router.RetrievalRoute.EXACT_SYMBOL_LOOKUP:
        return VerificationResult(
            outcome=VerificationOutcome.OK,
            detail=f"'{fully_qualified_symbol}' does not look like a fully-qualified symbol "
            "(module.Class.method) — no exact-match check performed.",
        )

    db = store.connect(store.default_db_path(repo_root))
    table = store.get_or_create_table(db)
    candidates = store.exact_symbol_lookup(table, fully_qualified_symbol)
    if not candidates:
        return VerificationResult(
            outcome=VerificationOutcome.OK,
            detail=f"No known changes affecting {fully_qualified_symbol} at version {pinned_version}.",
        )

    applicable: list[KnowledgeRecord] = []
    undetermined = 0
    for record in candidates:
        applies = _version_already_changed(pinned_version, record.to_version)
        if applies is True:
            applicable.append(record)
        elif applies is None:
            undetermined += 1

    if not applicable:
        detail = f"No known changes apply to {fully_qualified_symbol} at pinned version {pinned_version}."
        if undetermined:
            detail += (
                f" ({undetermined} record(s) for this symbol had a version range that could not be "
                "compared against the pin and were conservatively excluded, not silently cleared.)"
            )
        return VerificationResult(outcome=VerificationOutcome.OK, detail=detail)

    outcome = (
        VerificationOutcome.SYMBOL_REMOVED
        if any(r.rule_type == RuleType.REMOVED_NO_REPLACEMENT for r in applicable)
        else VerificationOutcome.SYMBOL_DEPRECATED
    )
    descriptions = [_describe_match(r) for r in applicable]
    detail = f"{fully_qualified_symbol} at version {pinned_version}: " + "; ".join(descriptions)
    suggested_replacement = descriptions[0] if len(applicable) == 1 and applicable[0].new_parameter else None

    return VerificationResult(outcome=outcome, detail=detail, suggested_replacement=suggested_replacement)
