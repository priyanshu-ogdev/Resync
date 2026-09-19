"""Unit tests for resolve/resolver.py's error-classification and pin-constraints logic, mocked at the
`subprocess.run` boundary — see test_resolver_integration.py for the real-`uv`-binary tests. Mocking here is
justified the same way tests/unit/test_verify_package.py justifies httpx.MockTransport: these tests exist to
prove resolver.py reacts correctly to each of uv's real, already-confirmed exit codes/output shapes (found
by actually running the binary — see resolver.py's own module docstring), not to re-prove uv's behavior
itself on every run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from resync.adapters.python.resolver import ResolvedDependency, ResolverError, ResolverUnavailableError, resolve

_SAMPLE_PYLOCK = """\
lock-version = "1.0"
created-by = "uv"
requires-python = ">=3.12"

[[packages]]
name = "requests"
version = "2.34.2"

[[packages]]
name = "urllib3"
version = "2.8.0"
"""


def _mock_run_writing(pylock_text: str, returncode: int = 0, stderr: str = ""):
    def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        if returncode == 0:
            out_path = Path(cmd[cmd.index("-o") + 1])
            out_path.write_text(pylock_text)
        return subprocess.CompletedProcess(cmd, returncode=returncode, stdout="", stderr=stderr)

    return _run


def test_resolve_parses_a_real_pylock_shape_into_dependencies(tmp_path: Path) -> None:
    with patch("subprocess.run", side_effect=_mock_run_writing(_SAMPLE_PYLOCK)):
        result = resolve(["requests"], tmp_path)
    assert result.dependencies == [
        ResolvedDependency(name="requests", version="2.34.2"),
        ResolvedDependency(name="urllib3", version="2.8.0"),
    ]


def test_resolve_raises_resolver_error_on_exit_code_1_not_found(tmp_path: Path) -> None:
    stderr = (
        "  × No solution found when resolving dependencies:\n"
        "  ╰─▶ Because fake-pkg was not found in the package registry..."
    )
    with patch("subprocess.run", side_effect=_mock_run_writing("", returncode=1, stderr=stderr)):
        with pytest.raises(ResolverError, match="fake-pkg"):
            resolve(["fake-pkg"], tmp_path)


def test_resolve_raises_resolver_unavailable_on_exit_code_2_network_failure(tmp_path: Path) -> None:
    stderr = "error: Request failed after 3 retries in 5.8s\n  Caused by: Failed to fetch: ..."
    with patch("subprocess.run", side_effect=_mock_run_writing("", returncode=2, stderr=stderr)):
        with pytest.raises(ResolverUnavailableError, match="registry"):
            resolve(["requests"], tmp_path)


def test_resolve_raises_resolver_unavailable_when_uv_missing_from_path(tmp_path: Path) -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("uv")):
        with pytest.raises(ResolverUnavailableError, match="PATH"):
            resolve(["requests"], tmp_path)


def test_resolve_raises_resolver_unavailable_on_timeout(tmp_path: Path) -> None:
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["uv"], timeout=1.0)):
        with pytest.raises(ResolverUnavailableError, match="did not finish"):
            resolve(["requests"], tmp_path, timeout_seconds=1.0)


def test_resolve_passes_pin_constraints_from_resync_toml(tmp_path: Path) -> None:
    (tmp_path / "resync.toml").write_text('[[pin]]\npackage = "urllib3"\nmax_version = "1.26.20"\nreason = "test"\n')
    captured_cmd: list[str] = []
    captured_constraints = {"text": ""}

    def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        captured_cmd.extend(cmd)
        constraints_path = Path(cmd[cmd.index("-c") + 1])
        captured_constraints["text"] = constraints_path.read_text()  # must read before the tmpdir is cleaned up
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_text(_SAMPLE_PYLOCK)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=_run):
        resolve(["requests"], tmp_path)

    assert "-c" in captured_cmd
    assert "urllib3<=1.26.20" in captured_constraints["text"]


def test_resolve_omits_constraints_flag_when_no_pins_declared(tmp_path: Path) -> None:
    captured_cmd: list[str] = []

    def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        captured_cmd.extend(cmd)
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_text(_SAMPLE_PYLOCK)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=_run):
        resolve(["requests"], tmp_path)

    assert "-c" not in captured_cmd
