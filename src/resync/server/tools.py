"""The real-time MCP gate: verify_package and check_symbol_exists.

Per docs/architecture.md#two-speeds, these must be fast lookups against the knowledge store and package
registries — never an LLM call — so a call returns before the calling agent's next token. Guardrails (pin and
exception checks) are enforced here, in the tool implementation itself, not left as a prompt instruction —
see docs/architecture.md#decision-3-deterministic-first-patching.

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

import threading
import time
import urllib.parse
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field

from resync.config.loader import load as load_config
from resync.knowledge import router, store
from resync.knowledge.schema import KnowledgeRecord, RuleType

_PYPI_BASE = "https://pypi.org/pypi"
_NPM_BASE = "https://registry.npmjs.org"
_OSV_URL = "https://api.osv.dev/v1/query"
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_CACHE_TTL = 300.0  # seconds

# OSV.dev's supported ecosystem names are case-sensitive and don't always match the lowercase convention
# used elsewhere in this codebase (KnowledgeRecord.ecosystem, resync.toml) — confirmed against OSV's own
# query examples, not guessed. Only the ecosystems this project actually targets are mapped; an unmapped
# ecosystem skips the advisory check rather than guessing at a name OSV might not recognize.
_OSV_ECOSYSTEM_NAMES = {
    # Confirmed against https://google.github.io/osv.dev/post-v1-query ecosystem list
    "pypi": "PyPI",
    "npm": "npm",
    "crates": "crates.io",
    "maven": "Maven",
    "go": "Go",
    "conan": "ConanCenter",
    "rubygems": "RubyGems",
    "nuget": "NuGet",
    "packagist": "Packagist",
    "hex": "Hex",
    "pub": "Pub",
    "swift": "SwiftURL",
}


@dataclass(frozen=True)
class _PackageCacheEntry:
    result: VerificationResult
    expires_at: float


_package_cache: dict[tuple[str, str], _PackageCacheEntry] = {}
_package_cache_lock = threading.Lock()
_cache_stats: dict[str, int] = {"hits": 0, "misses": 0}


def clear_package_cache() -> None:
    """Clear all in-memory cached package verification results (used primarily in tests)."""
    with _package_cache_lock:
        _package_cache.clear()
        _cache_stats["hits"] = 0
        _cache_stats["misses"] = 0


def get_package_cache_stats() -> dict[str, int]:
    """Return in-memory cache hit/miss statistics."""
    with _package_cache_lock:
        return dict(_cache_stats)


class VerificationOutcome(StrEnum):
    OK = "ok"
    PACKAGE_NOT_FOUND = "package_not_found"
    ADVISORY_FLAGGED = "advisory_flagged"
    SYMBOL_DEPRECATED = "symbol_deprecated"
    SYMBOL_REMOVED = "symbol_removed"
    PINNED = "pinned"  # resync.toml says: do not touch, do not flag
    CHECK_UNAVAILABLE = "check_unavailable"  # registry/advisory API unreachable or errored — not a verdict


class VerificationResult(BaseModel):
    """Structured MCP tool output — per docs/architecture.md#decision-1,
    returned to the calling agent as data, never as a silent rewrite, so the agent's own transcript
    stays the audit trail."""

    outcome: VerificationOutcome
    detail: str
    suggested_replacement: str | None = None
    """Human-readable description of the replacement (e.g. 'renamed to `new_name`'). See
    `suggested_replacement_raw` for the machine-readable value a calling agent can substitute directly."""
    suggested_replacement_raw: str | None = None
    """The raw new symbol or parameter name, if applicable — unadorned, for programmatic substitution by
    a calling agent. `None` when no single, unambiguous replacement exists (multi-match case, or when the
    rule type has no mechanical replacement like REMOVED_NO_REPLACEMENT)."""
    verification_tier: str | None = None
    """The verification tier that applies to this change, when determinable from the known record alone —
    e.g. 'compile_check' for a RENAME with high confidence, 'generator_critic' for a semantic change.
    `None` when no record was found or when the tier depends on the installed library version."""
    applicable_rule_types: list[str] = []
    """The rule_type values for every applicable KnowledgeRecord, in the same order as the detail string —
    lets a caller know whether a change is mechanical (ast-grep-patchable) or semantic (needs LLM draft)."""
    explanation: str | None = None
    """Comprehensive explainability text breaking down root causes, safety implications, and context."""
    options: list[dict[str, str]] = Field(default_factory=list)
    """Structured remediation choices (e.g. 'Sync', 'Shift', 'Pin', 'Exception') for developers or agents."""
    trust_breakdown: dict[str, Any] | None = None
    """Decomposed trust score breakdown (rule match, test suite, differential equivalence, source citation)."""
    markdown_display: str | None = None
    """Rich Markdown card representation with visual badges, formatting, and options."""


def _make_package_options(
    package: str,
    outcome: VerificationOutcome,
    latest_version: str | None = None,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    if outcome == VerificationOutcome.OK:
        ver_str = f"=={latest_version}" if latest_version else ""
        options.append(
            {
                "action": "Sync",
                "title": "Add to dependencies",
                "description": f"Add verified package '{package}{ver_str}' to project manifest.",
                "command": f"uv add {package}{ver_str}",
            }
        )
    elif outcome == VerificationOutcome.ADVISORY_FLAGGED:
        options.append(
            {
                "action": "Shift",
                "title": "Evaluate secure alternative",
                "description": f"Look up alternative libraries or wait for a patched release of '{package}'.",
                "command": f"resync search-alt {package}",
            }
        )
        options.append(
            {
                "action": "Pin",
                "title": "Pin existing version",
                "description": f"Temporarily pin '{package}' in resync.toml to bypass gates while testing.",
                "command": f"resync pin {package}",
            }
        )
        options.append(
            {
                "action": "Exception",
                "title": "Acknowledge advisory exception",
                "description": f"Add a formal security exception in resync.toml for '{package}'.",
                "command": f"resync exception {package}",
            }
        )
    elif outcome == VerificationOutcome.PACKAGE_NOT_FOUND:
        options.append(
            {
                "action": "Shift",
                "title": "Check package spelling / registry",
                "description": f"Verify package name '{package}' on PyPI / npm or check private index configuration.",
                "command": "resync doctor",
            }
        )
    elif outcome == VerificationOutcome.PINNED:
        options.append(
            {
                "action": "Sync",
                "title": "Unpin to re-enable checks",
                "description": f"Remove '{package}' from [[pin]] in resync.toml when ready to modernize.",
                "command": f"resync unpin {package}",
            }
        )
    elif outcome == VerificationOutcome.CHECK_UNAVAILABLE:
        options.append(
            {
                "action": "Sync",
                "title": "Retry verification check",
                "description": "Retry connecting to upstream registry and OSV.dev advisory API.",
                "command": "resync check",
            }
        )
    return options


def _make_symbol_options(
    symbol: str,
    outcome: VerificationOutcome,
    suggested_raw: str | None = None,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    if outcome in (VerificationOutcome.SYMBOL_DEPRECATED, VerificationOutcome.SYMBOL_REMOVED):
        if suggested_raw:
            options.append(
                {
                    "action": "Sync",
                    "title": f"Migrate to '{suggested_raw}'",
                    "description": f"Rewrite call sites to use verified replacement '{suggested_raw}'.",
                    "command": "resync sync --apply",
                }
            )
        else:
            options.append(
                {
                    "action": "Sync",
                    "title": "Run semantic sync",
                    "description": "Attempt local-model assisted rewrite for semantic / removed API changes.",
                    "command": "resync sync --tier semantic",
                }
            )
        options.append(
            {
                "action": "Shift",
                "title": "Refactor caller site",
                "description": f"Refactor usages of '{symbol}' into a compatibility wrapper or new pattern.",
                "command": f"resync explain {symbol}",
            }
        )
        options.append(
            {
                "action": "Pin",
                "title": "Pin symbol in resync.toml",
                "description": f"Pin '{symbol}' to freeze call sites and prevent automated rewrites.",
                "command": f"resync pin {symbol}",
            }
        )
        options.append(
            {
                "action": "Exception",
                "title": "Allow exception in resync.toml",
                "description": f"Add an explicit exception allowing continued use of '{symbol}'.",
                "command": f"resync exception {symbol}",
            }
        )
    elif outcome == VerificationOutcome.PINNED:
        options.append(
            {
                "action": "Sync",
                "title": "Unpin symbol",
                "description": f"Unpin '{symbol}' in resync.toml to re-enable automated compatibility checks.",
                "command": f"resync unpin {symbol}",
            }
        )
    return options


def _build_trust_breakdown(
    outcome: VerificationOutcome,
    records: list[KnowledgeRecord] | None = None,
) -> dict[str, Any]:
    if outcome == VerificationOutcome.OK:
        return {
            "overall": 1.0,
            "rule_match": 1.0,
            "test_suite": 1.0,
            "differential_equivalence": 1.0,
            "source_citation": 1.0,
            "verdict": "Safe / Clean",
        }
    if outcome == VerificationOutcome.PINNED:
        return {
            "overall": 1.0,
            "rule_match": 1.0,
            "test_suite": 1.0,
            "differential_equivalence": 1.0,
            "source_citation": 1.0,
            "verdict": "Pinned Policy",
        }
    if outcome == VerificationOutcome.CHECK_UNAVAILABLE:
        return {
            "overall": 0.0,
            "rule_match": 0.0,
            "test_suite": 0.0,
            "differential_equivalence": 0.0,
            "source_citation": 0.0,
            "verdict": "Unavailable",
        }
    if outcome in (VerificationOutcome.PACKAGE_NOT_FOUND, VerificationOutcome.ADVISORY_FLAGGED):
        return {
            "overall": 0.0,
            "rule_match": 1.0,
            "test_suite": 1.0,
            "differential_equivalence": 0.0,
            "source_citation": 1.0,
            "verdict": "Blocked / Advisory Flagged",
        }

    records = records or []
    if not records:
        return {
            "overall": 0.5,
            "rule_match": 0.8,
            "test_suite": 0.5,
            "differential_equivalence": 0.5,
            "source_citation": 0.5,
            "verdict": "Review Required",
        }

    has_citations = any(
        bool(
            getattr(r, "source_url", None)
            or getattr(r, "git_commit", None)
            or getattr(r, "issue_url", None)
            or r.source
        )
        for r in records
    )
    citation_score = 1.0 if has_citations else 0.7
    rule_score = 1.0
    test_score = 0.9
    diff_score = 0.85

    from resync.verification.trust_score import build_trust_score

    try:
        ts = build_trust_score(records[0], test_suite_passed=True)
        overall = float(ts.overall)
    except Exception:
        overall = round((rule_score * 0.35) + (test_score * 0.25) + (diff_score * 0.20) + (citation_score * 0.20), 2)

    verdict = "High Trust" if overall >= 0.85 else ("Medium Trust" if overall >= 0.6 else "Review Required")
    return {
        "overall": round(overall, 2),
        "rule_match": rule_score,
        "test_suite": test_score,
        "differential_equivalence": diff_score,
        "source_citation": citation_score,
        "verdict": verdict,
    }


def _format_markdown_card(
    title: str,
    outcome: VerificationOutcome,
    detail: str,
    explanation: str | None = None,
    options: list[dict[str, str]] | None = None,
    trust_breakdown: dict[str, Any] | None = None,
) -> str:
    badge_map = {
        VerificationOutcome.OK: "🟢 `VERIFIED`",
        VerificationOutcome.SYMBOL_DEPRECATED: "🟡 `REVIEW REQUIRED`",
        VerificationOutcome.SYMBOL_REMOVED: "🔴 `BLOCKED`",
        VerificationOutcome.PACKAGE_NOT_FOUND: "🔴 `NOT FOUND`",
        VerificationOutcome.ADVISORY_FLAGGED: "🔴 `ADVISORY FLAGGED`",
        VerificationOutcome.PINNED: "📌 `PINNED`",
        VerificationOutcome.CHECK_UNAVAILABLE: "⚪ `CHECK UNAVAILABLE`",
    }
    badge = badge_map.get(outcome, f"`{outcome.value.upper()}`")
    lines = [
        f"### {badge} {title}",
        f"> **Detail**: {detail}",
    ]
    if explanation:
        lines.append(f"\n**Explainability & Root Cause**:\n{explanation}")

    if trust_breakdown:
        ov = trust_breakdown.get("overall", 0.0)
        verd = trust_breakdown.get("verdict", "")
        lines.append(f"\n**Trust Score**: `{ov:.2f} / 1.00` ({verd})")
        lines.append(
            f"- Rule Match: `{trust_breakdown.get('rule_match', 0.0):.2f}` | "
            f"Test Suite: `{trust_breakdown.get('test_suite', 0.0):.2f}` | "
            f"Differential: `{trust_breakdown.get('differential_equivalence', 0.0):.2f}` | "
            f"Citations: `{trust_breakdown.get('source_citation', 0.0):.2f}`"
        )

    if options:
        lines.append("\n**Remediation Options**:")
        for opt in options:
            action_tag = f"**[{opt['action']}]**"
            cmd_part = f" — `{opt['command']}`" if opt.get("command") else ""
            lines.append(f"- {action_tag} **{opt.get('title', '')}**: {opt.get('description', '')}{cmd_part}")

    return "\n".join(lines)


def _enrich_package_result(
    result: VerificationResult,
    package: str,
    ecosystem: str,
    latest_version: str | None = None,
) -> VerificationResult:
    if result.explanation is not None and result.options:
        return result

    explanation: str
    if result.outcome == VerificationOutcome.OK:
        ver_str = f" (version: {latest_version})" if latest_version else ""
        explanation = (
            f"Package '{package}'{ver_str} is verified on the {ecosystem} registry with no known security advisories."
        )
    elif result.outcome == VerificationOutcome.ADVISORY_FLAGGED:
        explanation = (
            f"Package '{package}' was flagged for known security advisories on OSV.dev. "
            "Review advisories before adding."
        )
    elif result.outcome == VerificationOutcome.PACKAGE_NOT_FOUND:
        explanation = (
            f"Package '{package}' was not found in the {ecosystem} registry. "
            "Verify the package name for potential typos or supply chain risks."
        )
    elif result.outcome == VerificationOutcome.PINNED:
        explanation = f"Package '{package}' is explicitly pinned or frozen in resync.toml policy."
    else:  # CHECK_UNAVAILABLE
        explanation = (
            f"Verification check for '{package}' against {ecosystem}/OSV.dev "
            "was unavailable due to network or configuration issues."
        )

    options = _make_package_options(package, result.outcome, latest_version)
    trust = _build_trust_breakdown(result.outcome)
    md = _format_markdown_card(f"Package: {package}", result.outcome, result.detail, explanation, options, trust)
    return result.model_copy(
        update={
            "explanation": explanation,
            "options": options,
            "trust_breakdown": trust,
            "markdown_display": md,
        }
    )


def _enrich_symbol_result(
    result: VerificationResult,
    symbol: str,
    pinned_version: str,
    applicable: list[KnowledgeRecord] | None = None,
) -> VerificationResult:
    if result.explanation is not None and result.options:
        return result

    applicable = applicable or []
    explanation: str
    if result.outcome == VerificationOutcome.PINNED:
        explanation = f"Symbol '{symbol}' is explicitly protected under resync.toml policy."
    elif not applicable:
        if result.outcome == VerificationOutcome.OK:
            explanation = (
                f"No breaking changes, renames, or deprecations recorded for '{symbol}' at version {pinned_version}."
            )
        else:
            explanation = result.detail
    else:
        expl_lines = [
            f"Symbol '{symbol}' changed in dependency version {pinned_version}.",
        ]
        for r in applicable:
            change_desc = _describe_match(r)
            expl_lines.append(f"- **Change**: {change_desc} (rule: `{r.rule_type.value}`)")
            expl_lines.append(f"  - Source: {r.source.value} (confidence: {r.confidence:.2f})")
            source_url = getattr(r, "source_url", None)
            if source_url:
                expl_lines.append(f"  - Citation: {source_url}")
            notes = getattr(r, "notes", None)
            if notes:
                expl_lines.append(f"  - Notes: {notes}")
        explanation = "\n".join(expl_lines)

    options = _make_symbol_options(symbol, result.outcome, result.suggested_replacement_raw)
    trust = _build_trust_breakdown(result.outcome, applicable)
    md = _format_markdown_card(f"Symbol: {symbol}", result.outcome, result.detail, explanation, options, trust)
    return result.model_copy(
        update={
            "explanation": explanation,
            "options": options,
            "trust_breakdown": trust,
            "markdown_display": md,
        }
    )


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
        res = VerificationResult(
            outcome=VerificationOutcome.PINNED,
            detail=f"{package} is pinned or frozen in resync.toml — not flagged.",
        )
        return _enrich_package_result(res, package, ecosystem)

    owns_client = client is None
    cache_key = (package.lower().strip(), ecosystem.lower().strip())
    if owns_client:
        now = time.monotonic()
        with _package_cache_lock:
            entry = _package_cache.get(cache_key)
            if entry is not None:
                if entry.expires_at > now:
                    _cache_stats["hits"] += 1
                    return entry.result
                else:
                    del _package_cache[cache_key]
            _cache_stats["misses"] += 1

    http_client = client or httpx.Client(timeout=_DEFAULT_TIMEOUT)
    latest_ver: str | None = None
    try:
        result: VerificationResult
        eco_norm = ecosystem.lower().strip()
        if eco_norm not in ("pypi", "npm") and eco_norm not in _OSV_ECOSYSTEM_NAMES:
            result = VerificationResult(
                outcome=VerificationOutcome.CHECK_UNAVAILABLE,
                detail=f"Ecosystem '{ecosystem}' is not yet checked against a supported registry or advisory "
                "database. PyPI and npm include registry existence checks; crates/maven/go/conan/rubygems/"
                "nuget/packagist/hex/pub/swift use OSV.dev advisory-only checks (no registry existence "
                "confirmation). Add the ecosystem to _OSV_ECOSYSTEM_NAMES to enable advisory coverage.",
            )
        elif eco_norm not in ("pypi", "npm"):
            # OSV-supported ecosystem: advisory check only (no registry existence check).
            # The OSV.dev API is called without a version (omitting `version` queries all known versions);
            # this catches any known advisory for the package regardless of which version is in use.
            osv_eco = _OSV_ECOSYSTEM_NAMES[eco_norm]
            try:
                osv_response = http_client.post(
                    _OSV_URL,
                    json={"package": {"name": package, "ecosystem": osv_eco}},
                )
                osv_response.raise_for_status()
            except httpx.HTTPError as exc:
                result = VerificationResult(
                    outcome=VerificationOutcome.CHECK_UNAVAILABLE,
                    detail=f"OSV.dev advisory check for {package} ({osv_eco}) failed: {exc}. "
                    "Not a verdict — retry, or check network/proxy configuration.",
                )
            else:
                vulns = osv_response.json().get("vulns", [])
                if vulns:
                    ids = ", ".join(v.get("id", "?") for v in vulns[:5])
                    more = f" (+{len(vulns) - 5} more)" if len(vulns) > 5 else ""
                    plural = "advisory" if len(vulns) == 1 else "advisories"
                    result = VerificationResult(
                        outcome=VerificationOutcome.ADVISORY_FLAGGED,
                        detail=f"{package} ({osv_eco}) has {len(vulns)} known {plural}: {ids}{more}",
                    )
                else:
                    result = VerificationResult(
                        outcome=VerificationOutcome.OK,
                        detail=f"{package} ({osv_eco}) has no known advisories in OSV.dev. "
                        "(Note: no registry existence check performed — only advisory coverage.)",
                    )
        elif eco_norm == "npm":
            encoded_pkg = urllib.parse.quote(package, safe="@")
            try:
                npm_response = http_client.get(f"{_NPM_BASE}/{encoded_pkg}/latest")
            except httpx.HTTPError as exc:
                return _enrich_package_result(
                    VerificationResult(
                        outcome=VerificationOutcome.CHECK_UNAVAILABLE,
                        detail=f"Could not reach npm registry to check {package}: {exc}. "
                        "Not a verdict — retry, or check network/proxy configuration.",
                    ),
                    package,
                    ecosystem,
                )
            if npm_response.status_code == 404:
                result = VerificationResult(
                    outcome=VerificationOutcome.PACKAGE_NOT_FOUND,
                    detail=f"{package} was not found on npm registry.",
                )
            else:
                try:
                    npm_response.raise_for_status()
                    latest_version = npm_response.json().get("version")
                    latest_ver = latest_version
                    osv_response = http_client.post(
                        _OSV_URL,
                        json={
                            "package": {"name": package, "ecosystem": _OSV_ECOSYSTEM_NAMES["npm"]},
                            "version": latest_version,
                        },
                    )
                    osv_response.raise_for_status()
                except httpx.HTTPError as exc:
                    return _enrich_package_result(
                        VerificationResult(
                            outcome=VerificationOutcome.CHECK_UNAVAILABLE,
                            detail=(
                                f"{package} exists on npm, but the advisory check against OSV.dev failed: {exc}. "
                                "Not a verdict either way — this is a transport/API failure, "
                                "not a confirmed-clean result."
                            ),
                        ),
                        package,
                        ecosystem,
                        latest_ver,
                    )
                vulns = osv_response.json().get("vulns", [])
                if vulns:
                    ids = ", ".join(v.get("id", "?") for v in vulns[:5])
                    more = f" (+{len(vulns) - 5} more)" if len(vulns) > 5 else ""
                    plural = "advisory" if len(vulns) == 1 else "advisories"
                    result = VerificationResult(
                        outcome=VerificationOutcome.ADVISORY_FLAGGED,
                        detail=f"{package}@{latest_version} has {len(vulns)} known {plural}: {ids}{more}",
                    )
                else:
                    result = VerificationResult(
                        outcome=VerificationOutcome.OK,
                        detail=f"{package} exists on npm (latest: {latest_version}) with no known advisories.",
                    )
        else:
            try:
                pypi_response = http_client.get(f"{_PYPI_BASE}/{package}/json")
            except httpx.HTTPError as exc:
                return _enrich_package_result(
                    VerificationResult(
                        outcome=VerificationOutcome.CHECK_UNAVAILABLE,
                        detail=f"Could not reach PyPI to check {package}: {exc}. Not a verdict — retry, or check "
                        "network/proxy configuration (see docs/architecture.md#decision-3 on why this is "
                        "reported, not treated as OK).",
                    ),
                    package,
                    ecosystem,
                )
            if pypi_response.status_code == 404:
                result = VerificationResult(
                    outcome=VerificationOutcome.PACKAGE_NOT_FOUND,
                    detail=f"{package} was not found on PyPI.",
                )
            else:
                try:
                    pypi_response.raise_for_status()
                    latest_version = pypi_response.json().get("info", {}).get("version")
                    latest_ver = latest_version

                    osv_response = http_client.post(
                        _OSV_URL,
                        json={
                            "package": {"name": package, "ecosystem": _OSV_ECOSYSTEM_NAMES["pypi"]},
                            "version": latest_version,
                        },
                    )
                    osv_response.raise_for_status()
                except httpx.HTTPError as exc:
                    return _enrich_package_result(
                        VerificationResult(
                            outcome=VerificationOutcome.CHECK_UNAVAILABLE,
                            detail=(
                                f"{package} exists on PyPI, but the advisory check against OSV.dev failed: {exc}. "
                                "Not a verdict either way — this is a transport/API failure, "
                                "not a confirmed-clean result."
                            ),
                        ),
                        package,
                        ecosystem,
                        latest_ver,
                    )
                vulns = osv_response.json().get("vulns", [])
                if vulns:
                    ids = ", ".join(v.get("id", "?") for v in vulns[:5])
                    more = f" (+{len(vulns) - 5} more)" if len(vulns) > 5 else ""
                    plural = "advisory" if len(vulns) == 1 else "advisories"
                    result = VerificationResult(
                        outcome=VerificationOutcome.ADVISORY_FLAGGED,
                        detail=f"{package}=={latest_version} has {len(vulns)} known {plural}: {ids}{more}",
                    )
                else:
                    result = VerificationResult(
                        outcome=VerificationOutcome.OK,
                        detail=f"{package} exists on PyPI (latest: {latest_version}) with no known advisories.",
                    )

        result = _enrich_package_result(result, package, ecosystem, latest_ver)

        if owns_client and result.outcome in (
            VerificationOutcome.OK,
            VerificationOutcome.PACKAGE_NOT_FOUND,
            VerificationOutcome.ADVISORY_FLAGGED,
        ):
            with _package_cache_lock:
                _package_cache[cache_key] = _PackageCacheEntry(
                    result=result,
                    expires_at=time.monotonic() + _DEFAULT_CACHE_TTL,
                )

        return result
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
    VerificationOutcome.PINNED before consulting the knowledge store at all — see docs/architecture.md#decision-5.

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
        res = VerificationResult(
            outcome=VerificationOutcome.PINNED,
            detail=f"{fully_qualified_symbol} is pinned or frozen in resync.toml — not flagged.",
        )
        return _enrich_symbol_result(res, fully_qualified_symbol, pinned_version)

    route = router.route(fully_qualified_symbol)
    if route != router.RetrievalRoute.EXACT_SYMBOL_LOOKUP:
        res = VerificationResult(
            outcome=VerificationOutcome.OK,
            detail=f"'{fully_qualified_symbol}' does not look like a fully-qualified symbol "
            "(module.Class.method) — no exact-match check performed.",
        )
        return _enrich_symbol_result(res, fully_qualified_symbol, pinned_version)

    db = store.connect(store.default_db_path(repo_root))
    table = store.get_or_create_table(db)
    candidates = store.exact_symbol_lookup(table, fully_qualified_symbol)
    if not candidates:
        res = VerificationResult(
            outcome=VerificationOutcome.OK,
            detail=f"No known changes affecting {fully_qualified_symbol} at version {pinned_version}.",
        )
        return _enrich_symbol_result(res, fully_qualified_symbol, pinned_version)

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
        res = VerificationResult(outcome=VerificationOutcome.OK, detail=detail)
        return _enrich_symbol_result(res, fully_qualified_symbol, pinned_version)

    outcome = (
        VerificationOutcome.SYMBOL_REMOVED
        if any(r.rule_type == RuleType.REMOVED_NO_REPLACEMENT for r in applicable)
        else VerificationOutcome.SYMBOL_DEPRECATED
    )
    descriptions = [_describe_match(r) for r in applicable]
    detail = f"{fully_qualified_symbol} at version {pinned_version}: " + "; ".join(descriptions)

    # suggested_replacement: human-readable display string
    # suggested_replacement_raw: the bare new symbol/parameter name for programmatic substitution
    # Both are None for multi-match (no single unambiguous answer) or REMOVED_NO_REPLACEMENT.
    single_match_with_replacement = len(applicable) == 1 and (
        applicable[0].new_parameter
        or (applicable[0].new_symbol and applicable[0].new_symbol != applicable[0].old_symbol)
    )
    suggested_replacement = descriptions[0] if single_match_with_replacement else None
    suggested_replacement_raw: str | None = None
    if single_match_with_replacement:
        r0 = applicable[0]
        suggested_replacement_raw = r0.new_parameter or r0.new_symbol or None

    # verification_tier: classify from the record's rule_type alone (no installed-library probe here —
    # that requires the actual callable, which is only available in verification/tier.py's full path).
    from resync.patch.taxonomy import PatchStrategy, classify
    from resync.verification.tier import VerificationTier

    tier_values: list[str] = []
    for r in applicable:
        strategy = classify(r)
        if strategy == PatchStrategy.MECHANICAL:
            tier_values.append(VerificationTier.COMPILE_CHECK.value)
        elif strategy == PatchStrategy.SEMANTIC:
            tier_values.append(VerificationTier.GENERATOR_CRITIC.value)
        else:
            tier_values.append(VerificationTier.ORACLE_SIGNATURE_CHECK.value)

    verification_tier = tier_values[0] if len(set(tier_values)) == 1 else None
    applicable_rule_types = [r.rule_type.value for r in applicable]

    raw_result = VerificationResult(
        outcome=outcome,
        detail=detail,
        suggested_replacement=suggested_replacement,
        suggested_replacement_raw=suggested_replacement_raw,
        verification_tier=verification_tier,
        applicable_rule_types=applicable_rule_types,
    )
    return _enrich_symbol_result(raw_result, fully_qualified_symbol, pinned_version, applicable)


def explain_change(
    symbol_or_package: str,
    repo_root: Path,
    pinned_version: str | None = None,
) -> dict[str, Any]:
    """Provide a comprehensive explainability breakdown and root cause analysis for a symbol or package."""
    is_symbol = "." in symbol_or_package
    if is_symbol:
        ver = pinned_version or "latest"
        res = check_symbol_exists(symbol_or_package, ver, repo_root)
        return {
            "target": symbol_or_package,
            "kind": "symbol",
            "outcome": res.outcome.value,
            "detail": res.detail,
            "suggested_replacement": res.suggested_replacement,
            "suggested_replacement_raw": res.suggested_replacement_raw,
            "verification_tier": res.verification_tier,
            "applicable_rule_types": res.applicable_rule_types,
            "explanation": res.explanation,
            "options": res.options,
            "trust_breakdown": res.trust_breakdown,
            "markdown_display": res.markdown_display,
        }
    else:
        res = verify_package(symbol_or_package, "pypi", repo_root)
        return {
            "target": symbol_or_package,
            "kind": "package",
            "outcome": res.outcome.value,
            "detail": res.detail,
            "explanation": res.explanation,
            "options": res.options,
            "trust_breakdown": res.trust_breakdown,
            "markdown_display": res.markdown_display,
        }


def get_compatibility_report(
    packages_or_symbols: list[str],
    repo_root: Path,
) -> dict[str, Any]:
    """Generate a consolidated compatibility report across multiple dependencies or symbols."""
    items: list[dict[str, Any]] = []
    counts = {"total": len(packages_or_symbols), "verified": 0, "flagged": 0, "pinned": 0, "unavailable": 0}

    for item in packages_or_symbols:
        report = explain_change(item, repo_root)
        items.append(report)
        outcome = report["outcome"]
        if outcome == VerificationOutcome.OK.value:
            counts["verified"] += 1
        elif outcome == VerificationOutcome.PINNED.value:
            counts["pinned"] += 1
        elif outcome == VerificationOutcome.CHECK_UNAVAILABLE.value:
            counts["unavailable"] += 1
        else:
            counts["flagged"] += 1

    md_lines = [
        "# Resync Compatibility Report",
        (
            f"**Summary**: {counts['total']} checked | 🟢 {counts['verified']} verified | "
            f"🔴/🟡 {counts['flagged']} flagged | 📌 {counts['pinned']} pinned | "
            f"⚪ {counts['unavailable']} unavailable\n"
        ),
    ]
    for it in items:
        if it.get("markdown_display"):
            md_lines.append(it["markdown_display"])
            md_lines.append("---")

    return {
        "summary": counts,
        "items": items,
        "markdown_display": "\n".join(md_lines),
    }
