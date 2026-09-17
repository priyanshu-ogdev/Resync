"""Pydantic models for resync.toml.

See docs/adr/0005-config-and-policy-persistence.md for why this file exists and why every check against it
must happen before a potential issue is flagged, not after.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    mode: Literal["realtime", "scheduled", "hybrid"] = "hybrid"
    target_profile: str = "pinned"  # "latest" | "pinned" | "security-only" | "YYYY-MM"
    agents: list[str] = Field(default_factory=list)


class ScheduleConfig(BaseModel):
    mechanical: str = "daily"
    semantic: str = "weekly"
    critical_cve: str = "instant"


class ConfidenceConfig(BaseModel):
    auto_apply_above: float = Field(default=0.95, ge=0.0, le=1.0)
    review_required_below: float = Field(default=0.95, ge=0.0, le=1.0)


class Pin(BaseModel):
    """A version ceiling Resync must never propose upgrading past."""

    package: str
    max_version: str
    reason: str


class Exception_(BaseModel):
    """A file/symbol-level exception for deliberately frozen legacy code.

    `expires` is mandatory by design, not by convention — see docs/adr/0005: an exception with no forced
    re-review date is exactly the kind of silently-ignored warning this project exists to prevent.
    """

    path: str
    reason: str
    expires: date


class Policy(BaseModel):
    """A persisted sync-vs-shift decision from the Impact Map (docs/architecture.md#the-impact-map).

    Set once via the MCP `input_required` elicitation flow; matching future cases reuse this instead of
    asking again.
    """

    symbol: str
    change_type: str
    decision: Literal["sync", "shift"]
    confirmed_by: str
    last_confirmed: date


class AppliedFix(BaseModel):
    """A record that a specific mechanical fix was already applied to a specific file.

    This is the applied-already guard promised (but not yet built) in `ast_grep_runner.py`'s module
    docstring and `taxonomy.py`'s PatchStrategy.MECHANICAL caveat — the natural extension of the
    `[[policy]]` mechanism above, per docs/adr/0005: both exist to record "this was already decided or
    done, don't re-litigate it on the next scheduled pass."

    It exists specifically because REORDER is not naturally idempotent (ast_grep_runner.py's finding 7): a
    positional-swap pattern matches its own already-fixed output just as validly as the original broken
    code, so an unattended scheduled sweep would swap it back and forth forever with no external state to
    check against. RENAME doesn't strictly need this (the old name stops existing once fixed, so the
    pattern naturally stops matching), but the guard is written generically so any future non-idempotent
    mechanical rule type is protected by the same mechanism rather than a new one-off.

    `fingerprint` deliberately encodes the *specific transition* (e.g. host/port -> port/host), not just the
    symbol — so if a future library version reorders the same symbol's arguments again, that is a genuinely
    new fix and must not be silently skipped as "already applied".
    """

    file: str
    symbol: str
    change_type: str
    fingerprint: str
    applied_at: date


class ResyncConfig(BaseModel):
    """The full parsed contents of a resync.toml file."""

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    pin: list[Pin] = Field(default_factory=list)
    exception: list[Exception_] = Field(default_factory=list)
    policy: list[Policy] = Field(default_factory=list)
    applied: list[AppliedFix] = Field(default_factory=list)

    def is_pinned_or_frozen(self, symbol: str) -> bool:
        """The single check every code path must run before flagging a symbol as an issue.

        Checking this *before* raising a finding — not filtering findings after the fact — is what keeps
        intentionally-frozen code out of the trust dashboard entirely, per docs/adr/0005.
        """
        return any(p.package == symbol or symbol.startswith(p.package) for p in self.pin) or any(
            e.path == symbol for e in self.exception
        )

    def policy_for(self, symbol: str, change_type: str) -> Policy | None:
        return next(
            (p for p in self.policy if p.symbol == symbol and p.change_type == change_type),
            None,
        )

    def already_applied(self, file: str, symbol: str, change_type: str, fingerprint: str) -> bool:
        """The applied-already guard — see AppliedFix's docstring for why this exists.

        Matches on all four fields, not just (file, symbol): a *different* fingerprint for the same
        (file, symbol, change_type) means the upstream package changed the same symbol again since the
        last applied fix, which is a new, legitimate fix to apply, not a repeat of the old one.
        """
        return any(
            a.file == file and a.symbol == symbol and a.change_type == change_type and a.fingerprint == fingerprint
            for a in self.applied
        )
