"""Read and write resync.toml.

Reading uses the stdlib `tomllib` (Python 3.11+, read-only by design). Writing uses `tomli_w`, the standard
companion library, since the Impact Map's policy-persistence loop (docs/architecture.md#the-impact-map) needs
to append confirmed decisions back into the file, not just parse it once at startup.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

from resync.config.schema import AppliedFix, Policy, ResyncConfig

DEFAULT_FILENAME = "resync.toml"


def load(repo_root: Path) -> ResyncConfig:
    """Load resync.toml from a repo root, or return defaults if it doesn't exist yet.

    A missing file is not an error: a project with no resync.toml simply gets Resync's default behavior
    (hybrid mode, no pins, no exceptions) rather than being rejected outright.
    """
    path = repo_root / DEFAULT_FILENAME
    if not path.exists():
        return ResyncConfig()
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return ResyncConfig.model_validate(raw)


def persist_policy(repo_root: Path, policy: Policy) -> None:
    """Append a confirmed sync-vs-shift decision back into resync.toml.

    Called once, at the point a human answers the Impact Map's MCP `input_required` elicitation — see
    docs/adr/0005-config-and-policy-persistence.md. This must never silently overwrite an existing policy for
    the same (symbol, change_type) pair; a caller should check `ResyncConfig.policy_for` first.
    """
    config = load(repo_root)
    config.policy.append(policy)
    path = repo_root / DEFAULT_FILENAME
    with path.open("wb") as f:
        tomli_w.dump(config.model_dump(mode="json"), f)


def persist_applied_fix(repo_root: Path, applied_fix: AppliedFix) -> None:
    """Append a record of an applied mechanical fix back into resync.toml.

    Called by patch/ast_grep_runner.py's apply() right after a non-idempotent mechanical fix (currently
    only REORDER) is successfully written to disk — see AppliedFix's docstring for why this exists and
    docs/adr/0005 for why resync.toml, not a separate side-car file, is the persistence layer: it's the
    same "confirmed decisions live here" contract `persist_policy` already established, kept in one place
    rather than split across two files a reviewer would have to cross-reference.

    Mirrors persist_policy's read-modify-write shape deliberately, for the same reason: this must never
    silently overwrite prior applied-fix history, only append to it.
    """
    config = load(repo_root)
    config.applied.append(applied_fix)
    path = repo_root / DEFAULT_FILENAME
    with path.open("wb") as f:
        tomli_w.dump(config.model_dump(mode="json"), f)
