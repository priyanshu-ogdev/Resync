"""Read and write resync.toml.

Reading uses the stdlib `tomllib` (Python 3.11+, read-only by design). Writing uses `tomli_w`, the standard
companion library, since the Impact Map's policy-persistence loop (docs/architecture.md#the-impact-map) needs
to append confirmed decisions back into the file, not just parse it once at startup.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

from resync.config.schema import Policy, ResyncConfig

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
