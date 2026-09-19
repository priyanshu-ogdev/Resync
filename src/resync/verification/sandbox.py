"""Phase 3.3: sandbox execution wrapper for verification/differential.py's calls.

Every call in differential.py executes arbitrary target-repo code, including whatever the target repo's own
dependencies do at import/call time. That's untrusted code from resync's perspective — unlike resync's own
test suite — and needs isolation resync's own code doesn't.

`sandbox-runtime` (PyPI, 0.2.0 at time of writing) was confirmed real and installable, and its actual exposed
API confirmed to match what `docs/tech-stack.md` described (`SandboxManager`, `SandboxRuntimeConfig`,
`NetworkRestrictionConfig`, `FilesystemConfig`) — during Phase 2's sealing, not assumed here. Given its early
version number, a Docker+gVisor fallback is provided behind the same interface, selected explicitly via
`resync.toml` rather than silently swapped — an operator running this against real, untrusted third-party
code should know which isolation mechanism actually ran.

**Not exercised end-to-end in this development environment, honestly, not silently**: no network access here
to `uv sync --extra server` and pull `sandbox-runtime` itself, nor Docker available in this sandboxed review
environment to prove the gVisor fallback path. `SandboxRunner`'s two backends are both implemented and
unit-tested against their *selection and dispatch* logic (does the right backend get chosen, are the config
objects constructed correctly), not against a live isolated execution — that gap is tracked here explicitly,
mirroring the same honesty pattern already used for `embeddings.py`'s live model call and
`extract_api_diff.py`'s live griffe call.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


class SandboxBackend(StrEnum):
    SANDBOX_RUNTIME = "sandbox_runtime"
    """The primary backend. Requires `sandbox-runtime` (the `server` extra)."""

    DOCKER_GVISOR = "docker_gvisor"
    """Fallback, given sandbox-runtime's early version number. Requires a local `docker` with a `runsc`
    (gVisor) runtime configured — this module does not install or configure gVisor itself, only shells out
    to an already-configured `docker run --runtime=runsc`."""


@dataclass
class SandboxConfig:
    backend: SandboxBackend = SandboxBackend.SANDBOX_RUNTIME
    """Which backend to use — read from `resync.toml`'s `[project]` table in the real caller, not decided
    here; this module never silently falls back from one to the other on its own, per the module docstring's
    "an operator should know which isolation mechanism actually ran" principle."""

    allow_network: bool = False
    """A differential call has no legitimate reason to reach the network — default deny."""

    readonly_repo_path: Path | None = None
    """The target repo, mounted read-only. `None` is valid for calls that don't need repo filesystem access
    at all (e.g. a pure signature-bind check against an already-imported callable)."""


class SandboxUnavailableError(RuntimeError):
    """Raised when the selected backend's actual dependency (the `sandbox-runtime` package, or a working
    `docker`+`runsc`) isn't present. Distinct from a failure *inside* the sandboxed call, which should
    surface as whatever exception the sandboxed code itself raised, not this one.
    """


def run_in_sandbox(func: Callable[[], T], config: SandboxConfig) -> T:
    """Run `func` (a zero-argument closure — callers should `functools.partial`/close over whatever
    arguments `differential.py`'s checks need) inside the configured sandbox backend, and return its result.

    Deliberately a thin dispatcher, not a reimplementation: `sandbox-runtime` and Docker+gVisor each already
    solve process isolation correctly; this function's only job is picking the right one and wiring
    `SandboxConfig` into each backend's real config shape.
    """
    if config.backend == SandboxBackend.SANDBOX_RUNTIME:
        return _run_via_sandbox_runtime(func, config)
    return _run_via_docker_gvisor(func, config)


def _run_via_sandbox_runtime(func: Callable[[], T], config: SandboxConfig) -> T:
    try:
        from sandbox_runtime import (
            FilesystemConfig,
            NetworkRestrictionConfig,
            SandboxManager,
            SandboxRuntimeConfig,
        )
    except ImportError as exc:
        raise SandboxUnavailableError(
            "sandbox-runtime is not installed (the `server` extra) — run `uv sync --extra server`, or set "
            "SandboxConfig.backend=SandboxBackend.DOCKER_GVISOR if sandbox-runtime genuinely isn't an option"
        ) from exc

    runtime_config = SandboxRuntimeConfig(
        network=NetworkRestrictionConfig(allow_network=config.allow_network),
        filesystem=FilesystemConfig(
            readonly_paths=[str(config.readonly_repo_path)] if config.readonly_repo_path else [],
        ),
    )
    with SandboxManager(runtime_config) as sandbox:
        return sandbox.run(func)  # type: ignore[no-any-return]


def _run_via_docker_gvisor(func: Callable[[], T], config: SandboxConfig) -> T:
    """Fallback path. Unlike the primary backend, this can't literally ship an arbitrary Python closure into
    a container — it serializes `func`'s *call*, not `func` itself, via a small runner script executed with
    `cloudpickle` inside the container. Kept intentionally simple (one function, one result) rather than a
    general-purpose RPC layer, since this is a fallback for an early-version primary path, not a permanent
    parallel implementation to maintain at equal sophistication.
    """
    try:
        import cloudpickle
    except ImportError as exc:
        raise SandboxUnavailableError(
            "the Docker+gVisor fallback needs `cloudpickle` to serialize the call across the container "
            "boundary — add it to the `server` extra if this fallback is actually needed"
        ) from exc

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        call_path = tmp_path / "call.pkl"
        result_path = tmp_path / "result.pkl"
        call_path.write_bytes(cloudpickle.dumps(func))

        runner_script = tmp_path / "_run.py"
        runner_script.write_text(
            "import cloudpickle\n"
            "func = cloudpickle.loads(open('/sandbox/call.pkl', 'rb').read())\n"
            "result = func()\n"
            "open('/sandbox/result.pkl', 'wb').write(cloudpickle.dumps(result))\n"
        )

        mounts = ["-v", f"{tmp_path}:/sandbox:rw"]
        if config.readonly_repo_path is not None:
            mounts += ["-v", f"{config.readonly_repo_path}:/repo:ro"]
        network_flag = [] if config.allow_network else ["--network", "none"]

        cmd = [
            "docker",
            "run",
            "--rm",
            "--runtime=runsc",
            *network_flag,
            *mounts,
            "python:3.12-slim",
            "python",
            "/sandbox/_run.py",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except FileNotFoundError as exc:
            # subprocess.run doesn't distinguish "docker isn't installed" from other launch failures with
            # its own exception type — it just lets the OS-level FileNotFoundError propagate. Left uncaught,
            # that's exactly the "crash with an unrelated exception type" this function's docstring and
            # tests/unit/test_sandbox.py promise never happens. Caught here and normalized to the same
            # documented SandboxUnavailableError as the missing-cloudpickle case above.
            raise SandboxUnavailableError(
                "the Docker+gVisor fallback needs the `docker` CLI on PATH, and it isn't available here "
                f"({exc})"
            ) from exc
        if proc.returncode != 0:
            raise SandboxUnavailableError(
                f"docker+gvisor sandbox exited non-zero ({proc.returncode}): {proc.stderr.strip()[:2000]}"
            )
        if not result_path.exists():
            raise SandboxUnavailableError(
                "docker+gvisor sandbox produced no result file — the sandboxed call likely raised before "
                "writing output; see stdout/stderr above"
            )
        result: Any = cloudpickle.loads(result_path.read_bytes())
        return result  # type: ignore[no-any-return]
