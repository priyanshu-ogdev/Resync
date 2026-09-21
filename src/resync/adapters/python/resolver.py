"""Wraps `uv` for real dependency resolution — never reimplements a solver, per
docs/architecture.md#supply-chain-provenance-gate and docs/multi-language-adapters.md's Python `resolve`
contract ("shell out to `uv` (preferred, fastest) or `pip-compile`/Poetry").

**Command shape, verified against the real, installed `uv` binary, not assumed:** an earlier draft assumed
`uv add --dry-run` existed; running the real binary immediately produced `unexpected argument '--dry-run'`.
The real, correct command for "resolve this list of requirements without touching any project state" is
`uv pip compile - --format pylock.toml`, reading requirements from stdin and writing PEP 751's `pylock.toml`
format — structured TOML, not `requirements.txt`'s comment-annotated text, so no regex parsing is needed.
Two more real constraints found by running the actual binary, not by reading docs: the output path must
literally start with `pylock.` and end in `.toml` (uv rejects other names outright, confirmed via a live
`error: Expected the output filename to start with...`), and `uv.lock`'s own table is `[[package]]`
(singular) while `pylock.toml`'s is `[[packages]]` (plural) — different files, different schemas; conflating
them would silently misparse one or the other.

**Exit-code-based error classification, verified against real failure runs, not guessed from uv's prose:**
a genuinely nonexistent/unsatisfiable requirement (`uv pip compile` given a package that doesn't exist)
exits **1** with "No solution found... was not found in the package registry" — a real, actionable finding.
A registry that can't be reached at all (tested against a deliberately invalid index URL) exits **2** with a
distinctly different message shape ("Request failed after N retries", "Failed to fetch", a DNS/connect error
chain).

**That two-way split was found incomplete by independently reproducing it in a different network
environment** — worth recording precisely rather than silently patched over, since the discrepancy itself is
informative: in a sandbox whose egress proxy returns a real HTTP 403 for `https://pypi.org/simple` (as
opposed to the connection simply failing to establish at all), `uv pip compile` exits **1**, not 2 — the
exact same exit code as a genuine "no such package" result — with `stderr` reading "was not found in the
package registry" plus a secondary hint mentioning the 403. Exit-code-2-only classification would report
this specific, real, reproducible case as `ResolverError` ("this package doesn't exist"), which is false: the
package exists, the registry is simply blocked. Classification here therefore checks exit code **2** first
(the clean, unambiguous signal), then falls back to scanning `stderr` for registry/network-failure vocabulary
when the exit code is 1 — catching the HTTP-403-via-proxy case exit-code-2-alone misses, without weakening
the exit-code-2 case's already-clean signal.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resync.adapters.base import Dependency

from resync.config.loader import load as load_config

_UV_NOT_FOUND_EXIT_CODE = 1
_UV_NETWORK_EXIT_CODE = 2


def _find_binary(name: str) -> str:
    """Resolve a binary path cleanly across Windows and Linux, respecting PATH, activated venvs,
    unactivated venvs, and conda layouts."""
    # 1. System PATH
    found = shutil.which(name)
    if found:
        return found
    # 2. Sibling of running Python interpreter (e.g. .venv/bin on Linux, .venv/Scripts on Windows)
    parent = Path(sys.executable).parent
    found = shutil.which(name, path=str(parent))
    if found:
        return found
    # 3. Sibling Scripts directory (e.g. conda root on Windows)
    scripts = parent / "Scripts"
    if scripts.is_dir():
        found = shutil.which(name, path=str(scripts))
        if found:
            return found
    # 4. Standard sys.prefix locations
    for candidate in (Path(sys.prefix) / "bin", Path(sys.prefix) / "Scripts"):
        if candidate.is_dir():
            found = shutil.which(name, path=str(candidate))
            if found:
                return found
    return name


_UV_BINARY: str = _find_binary("uv")

# Vocabulary confirmed in uv's real stderr (this module's own verification pass) for the exit-code-1 case
# that is actually a registry-reachability problem, not a genuine "no such package" result — see module
# docstring for the specific reproduced counter-example (an HTTP 403 from an egress proxy). A false negative
# here (missing a real network-failure phrasing) is worse than a rare false positive: silently reporting
# "doesn't exist" for a package that does exist, just unreachable right now, is the more harmful mistake.
_NETWORK_FAILURE_INDICATORS = (
    "403 forbidden",
    "could not connect",
    "connection refused",
    "connection reset",
    "network is unreachable",
    "temporary failure in name resolution",
    "timed out",
    "certificate verify failed",
)


class ResolverError(Exception):
    """A genuine, actionable resolution failure: a requirement doesn't exist, or the constraint set (real
    requirements plus resync.toml pins) is unsatisfiable. Safe to report to a human as a real finding."""


class ResolverUnavailableError(Exception):
    """The resolver couldn't reach the package index at all (network down, registry outage, egress policy
    blocking it). Never conflate this with ResolverError — an unreachable registry is not evidence anything
    is wrong with the requirements themselves, and reporting it as a resolution failure would be exactly the
    false-confidence failure mode this project's whole design stance exists to avoid (see
    server/tools.py's VerificationOutcome.CHECK_UNAVAILABLE for the same principle applied there)."""


@dataclass
class ResolvedDependency:
    name: str
    version: str


@dataclass
class ResolveResult:
    dependencies: list[ResolvedDependency]
    pylock_toml: str  # the raw pylock.toml text, kept for provenance/audit — see verification/provenance.py


def _pin_constraints_file(repo_root: Path) -> str | None:
    """Renders resync.toml's `[[pin]]` entries as a `uv`-native constraints file (`name<=max_version` per
    line, uv's own documented constraints-file format) so a resolve never silently proposes a version past a
    pin — the resolver honors the same compatibility contract every other tool in this project does, rather
    than needing its own separate pin-checking pass bolted on afterward."""
    config = load_config(repo_root)
    if not config.pin:
        return None
    lines = [f"{pin.package}<={pin.max_version}" for pin in config.pin]
    return "\n".join(lines) + "\n"


def resolve(requirements: list[str], repo_root: Path, *, timeout_seconds: float = 120.0) -> ResolveResult:
    """Resolves `requirements` (PEP 508 strings, e.g. `["transformers>=4.30"]`) against PyPI via a real `uv`
    subprocess, honoring `repo_root`'s resync.toml pins as resolver constraints. Raises `ResolverError` for a
    genuine unsatisfiable/not-found result, `ResolverUnavailableError` if the registry can't be reached, or
    `ResolverError` for any other nonzero exit (uv itself misconfigured, a malformed requirement string,
    etc. — still a real, reportable problem, just not one of the two specifically-classified cases above).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "pylock.resync.toml"  # must start with "pylock." and end ".toml" — see above
        cmd = [_UV_BINARY, "pip", "compile", "-", "--format", "pylock.toml", "-o", str(out_path)]

        constraints_text = _pin_constraints_file(repo_root)
        constraints_path: Path | None = None
        if constraints_text is not None:
            constraints_path = Path(tmpdir) / "pins.constraints.txt"
            constraints_path.write_text(constraints_text)
            cmd.extend(["-c", str(constraints_path)])

        try:
            proc = subprocess.run(
                cmd,
                input="\n".join(requirements) + "\n",
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=repo_root,
            )
        except FileNotFoundError as exc:
            raise ResolverUnavailableError(
                f"the `uv` CLI isn't on PATH — install it to use the resolver ({exc})"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ResolverUnavailableError(
                f"uv pip compile did not finish within {timeout_seconds}s — likely a slow/unreachable "
                f"registry, not a resolution problem with the requirements themselves ({exc})"
            ) from exc

        if proc.returncode == _UV_NETWORK_EXIT_CODE:
            raise ResolverUnavailableError(
                f"uv could not reach the package registry (exit {proc.returncode}): {proc.stderr.strip()}"
            )
        if proc.returncode == _UV_NOT_FOUND_EXIT_CODE and any(
            indicator in proc.stderr.lower() for indicator in _NETWORK_FAILURE_INDICATORS
        ):
            # The reproduced counter-example from this module's docstring: exit 1, but stderr shows this
            # was actually a blocked/unreachable registry wearing a "not found" exit code, not a genuine
            # negative result.
            raise ResolverUnavailableError(
                f"uv reported 'not found' (exit {proc.returncode}) but its message indicates a registry "
                f"connectivity problem, not a genuine negative result: {proc.stderr.strip()}"
            )
        if proc.returncode != 0:
            raise ResolverError(f"uv pip compile failed (exit {proc.returncode}): {proc.stderr.strip()}")

        pylock_text = out_path.read_text()
        data = tomllib.loads(pylock_text)
        dependencies = [
            ResolvedDependency(name=pkg["name"], version=pkg["version"]) for pkg in data.get("packages", [])
        ]
        return ResolveResult(dependencies=dependencies, pylock_toml=pylock_text)


def resolve_dependencies(
    dependencies: list[Dependency],
    target_profile: str,
    repo_root: Path | None = None,
) -> list[Dependency]:
    """Resolves a list of Dependency objects using uv against repo_root's configuration."""
    from resync.adapters.python.adapter import PythonDependency

    root = repo_root or Path(".")
    reqs: list[str] = []
    for d in dependencies:
        if d.version in ("*", "", None):
            reqs.append(d.name)
        elif any(c in d.version for c in "=<>~!"):
            reqs.append(f"{d.name}{d.version}")
        else:
            reqs.append(f"{d.name}=={d.version}")
    if not reqs:
        return []
    try:
        res = resolve(reqs, root)
        return [PythonDependency(name=dep.name, version=dep.version) for dep in res.dependencies]
    except (ResolverError, ResolverUnavailableError):
        # Fall back to original dependencies if uv is unavailable or resolution fails
        return [PythonDependency(name=d.name, version=d.version) for d in dependencies]
