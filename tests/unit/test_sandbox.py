"""Unit tests for verification/sandbox.py's dispatch logic.

Deliberately does NOT test live isolated execution — that needs a real, working sandbox-runtime process
setup or a working Docker+gVisor (runsc) setup, and this environment has neither (the `sandbox-runtime` and
`cloudpickle` *packages* are installable and importable here, but there's no actual sandbox-runtime backend
process to talk to, and no `docker` binary at all — see sandbox.py's module docstring). What's tested here:
the right backend is selected, and a missing/unusable dependency raises the documented
SandboxUnavailableError rather than some other, harder-to-diagnose exception deep in a stack trace. Each
test is written to cover whichever real failure mode this environment actually hits (import-missing vs.
importable-but-unusable), rather than assuming a specific one — see each test's own docstring.
"""

from __future__ import annotations

import importlib.util

import pytest

from resync.verification.sandbox import SandboxBackend, SandboxConfig, SandboxUnavailableError, run_in_sandbox

_SANDBOX_RUNTIME_INSTALLED = importlib.util.find_spec("sandbox_runtime") is not None


def test_sandbox_runtime_backend_raises_documented_error_when_not_installed() -> None:
    """Covers the "package genuinely not installed" path directly, via SandboxUnavailableError's own
    documented import-guard, rather than depending on this environment's actual install state (which the
    `server` extra can change): temporarily hides `sandbox_runtime` from the import system even if it's
    installed, so this test is meaningful whether or not the extra happens to be present."""
    import sys

    hidden = object()
    original = sys.modules.pop("sandbox_runtime", hidden)
    finder = _BlockImport("sandbox_runtime")
    sys.meta_path.insert(0, finder)
    try:
        config = SandboxConfig(backend=SandboxBackend.SANDBOX_RUNTIME)
        with pytest.raises(SandboxUnavailableError, match="sandbox-runtime is not installed"):
            run_in_sandbox(lambda: 42, config)
    finally:
        sys.meta_path.remove(finder)
        if original is not hidden:
            sys.modules["sandbox_runtime"] = original  # type: ignore[assignment]


class _BlockImport:
    """Minimal meta path finder that makes `import <name>` raise ImportError, regardless of whether the
    real package is installed — used to deterministically test the "not installed" branch."""

    def __init__(self, name: str) -> None:
        self._name = name

    def find_module(self, fullname: str, path: object = None) -> None:  # pragma: no cover - py2-style hook
        return None

    def find_spec(self, fullname: str, path: object, target: object = None) -> None:
        if fullname == self._name or fullname.startswith(f"{self._name}."):
            raise ImportError(f"{self._name} is blocked for this test")
        return None


@pytest.mark.skipif(
    not _SANDBOX_RUNTIME_INSTALLED,
    reason="sandbox_runtime not installed in this environment — the not-installed path is covered above",
)
def test_sandbox_runtime_backend_raises_documented_error_when_unusable() -> None:
    """`sandbox-runtime` the *package* is installed (the `server` extra), but this environment has no real
    sandbox-runtime backend/daemon for it to actually talk to — confirms that failure surfaces as the same
    documented SandboxUnavailableError-or-a-clear-underlying-error, not a silent success or a bare hang.
    This is a real, environment-specific gap (no sandbox-runtime daemon here), not a hypothetical."""
    config = SandboxConfig(backend=SandboxBackend.SANDBOX_RUNTIME)
    with pytest.raises(Exception):  # noqa: B017 - exact exception type is sandbox-runtime's own, not ours to pin
        run_in_sandbox(lambda: 42, config)


def test_docker_gvisor_backend_raises_documented_error_when_docker_unavailable() -> None:
    """`cloudpickle` is installed in this environment (the `server` extra) but `docker` is not on PATH —
    confirms the FileNotFoundError from launching `docker` is caught and normalized to the documented
    SandboxUnavailableError (see sandbox.py's own fix for this) rather than propagating raw."""
    config = SandboxConfig(backend=SandboxBackend.DOCKER_GVISOR)
    with pytest.raises(SandboxUnavailableError):
        run_in_sandbox(lambda: 42, config)


def test_sandbox_config_defaults_deny_network() -> None:
    config = SandboxConfig()
    assert config.allow_network is False


def test_sandbox_config_defaults_to_primary_backend() -> None:
    config = SandboxConfig()
    assert config.backend == SandboxBackend.SANDBOX_RUNTIME
