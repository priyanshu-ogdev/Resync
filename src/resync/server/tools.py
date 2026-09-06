"""The real-time MCP gate: verify_package and check_symbol_exists.

Per docs/architecture.md#two-speeds, these must be fast lookups against the knowledge store and package
registries — never an LLM call — so a call returns before the calling agent's next token. Guardrails (pin and
exception checks) are enforced here, in the tool implementation itself, not left as a prompt instruction —
see docs/adr/0003-deterministic-first-patching.md.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from resync.config.loader import load as load_config


class VerificationOutcome(StrEnum):
    OK = "ok"
    PACKAGE_NOT_FOUND = "package_not_found"
    ADVISORY_FLAGGED = "advisory_flagged"
    SYMBOL_DEPRECATED = "symbol_deprecated"
    SYMBOL_REMOVED = "symbol_removed"
    PINNED = "pinned"  # resync.toml says: do not touch, do not flag


class VerificationResult(BaseModel):
    """Structured MCP tool output — per docs/adr/0001, returned to the calling agent as data, never as a
    silent rewrite, so the agent's own transcript stays the audit trail."""

    outcome: VerificationOutcome
    detail: str
    suggested_replacement: str | None = None


def verify_package(package: str, ecosystem: str, repo_root: Path) -> VerificationResult:
    """MCP tool: called before an agent writes a new import or dependency addition.

    TODO(baseline): wire to the registry existence check, the OSV.dev / GitHub Advisory lookup
    (docs/architecture.md#supply-chain-provenance-gate), and the knowledge store.
    """
    raise NotImplementedError


def check_symbol_exists(
    fully_qualified_symbol: str, pinned_version: str, repo_root: Path
) -> VerificationResult:
    """MCP tool: called before an agent calls a function from an existing dependency.

    Must check resync.toml pins/exceptions first (via ResyncConfig.is_pinned_or_frozen) and short-circuit to
    VerificationOutcome.PINNED before consulting the knowledge store at all — see
    docs/adr/0005-config-and-policy-persistence.md.

    TODO(baseline): wire to the knowledge store lookup for the pinned_version in question.
    """
    config = load_config(repo_root)
    if config.is_pinned_or_frozen(fully_qualified_symbol):
        return VerificationResult(
            outcome=VerificationOutcome.PINNED,
            detail=f"{fully_qualified_symbol} is pinned or frozen in resync.toml — not flagged.",
        )
    raise NotImplementedError
