"""Unit tests for llm/llama_server.py.

The real subprocess-spawn/health-poll path against a genuine `llama-server` binary + GGUF model cannot run
here (no network to fetch either) — see that module's docstring for the honest account. What's tested: argv
construction against the real, cited flag names; the one thing genuinely testable without the real binary
(a nonexistent binary name failing with the documented error, exactly the same real-binary-adjacent pattern
used in resolve/resolver.py and verification/sandbox.py); and the health-polling loop's logic against a
mocked HTTP layer and a fake (non-llama-server) subprocess this test controls directly.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from resync.llm.llama_server import (
    LlamaServerConfig,
    LlamaServerUnavailableError,
    _OutputDrainer,
    _wait_until_healthy,
    start,
)


def test_argv_includes_all_configured_flags_using_the_real_verified_names() -> None:
    config = LlamaServerConfig(
        model_path=Path("/models/qwen.gguf"), port=8081, n_gpu_layers=20, ctx_size=8192, alias="resync-coder"
    )
    argv = config.to_argv()
    assert argv == [
        "llama-server",
        "-m",
        str(Path("/models/qwen.gguf")),
        "--host",
        "127.0.0.1",
        "--port",
        "8081",
        "--n-gpu-layers",
        "20",
        "--ctx-size",
        "8192",
        "--alias",
        "resync-coder",
    ]


def test_argv_omits_unset_optional_flags_rather_than_passing_placeholders() -> None:
    config = LlamaServerConfig(model_path=Path("/models/qwen.gguf"))
    argv = config.to_argv()
    assert "--n-gpu-layers" not in argv
    assert "--ctx-size" not in argv
    assert "--alias" not in argv


def test_extra_args_are_appended_verbatim() -> None:
    config = LlamaServerConfig(model_path=Path("/models/qwen.gguf"), extra_args=["--verbose", "--seed", "42"])
    assert config.to_argv()[-3:] == ["--verbose", "--seed", "42"]


def test_missing_binary_raises_the_documented_error_not_a_raw_oserror(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")
    config = LlamaServerConfig(model_path=model)
    with pytest.raises(LlamaServerUnavailableError, match="not on PATH"):
        start(config, binary="definitely-not-a-real-binary-xyz")


def test_missing_model_file_is_caught_before_ever_spawning_a_process(tmp_path: Path) -> None:
    config = LlamaServerConfig(model_path=tmp_path / "does-not-exist.gguf")
    with pytest.raises(LlamaServerUnavailableError, match="model file not found"):
        # "python" is a real binary that exists on any machine running these tests — proves this check
        # fires before subprocess.Popen is even attempted, not that "python" happens to fail identically.
        start(config, binary=sys.executable)


def test_wait_until_healthy_returns_once_health_endpoint_reports_ok() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    drainer = _OutputDrainer(process)
    drainer.start()
    try:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            if calls["count"] < 2:
                raise httpx.ConnectError("not up yet")
            return httpx.Response(200, json={"status": "ok"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        _wait_until_healthy(process, "http://fake", timeout=5.0, client=client, drainer=drainer)
        assert calls["count"] >= 2  # confirms it actually polled more than once, not a lucky first hit
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_wait_until_healthy_raises_if_process_exits_before_healthy() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(1)"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    drainer = _OutputDrainer(process)
    drainer.start()
    process.wait(timeout=5)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not poll health once the process has already exited")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(LlamaServerUnavailableError, match="exited with code"):
        _wait_until_healthy(process, "http://fake", timeout=5.0, client=client, drainer=drainer)


def test_wait_until_healthy_times_out_and_kills_the_process_if_never_healthy() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    drainer = _OutputDrainer(process)
    drainer.start()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("never comes up")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    start_time = time.monotonic()
    with pytest.raises(LlamaServerUnavailableError, match="did not become healthy"):
        _wait_until_healthy(process, "http://fake", timeout=1.0, client=client, drainer=drainer)
    assert time.monotonic() - start_time < 5.0  # didn't hang past the configured timeout
    assert process.poll() is not None  # confirms the timeout path actually cleaned up the process


def test_output_drainer_prevents_a_real_pipe_deadlock_on_verbose_child_output() -> None:
    """Regression test for a real, previously-undetected bug (see _OutputDrainer's own docstring): a child
    process writing more than the OS pipe buffer's worth of combined stdout+stderr would block on `write()`
    forever if nothing reads the pipe concurrently. This spawns a real child that writes ~200KB (well past
    the ~64KB Linux default) in a tight loop with no sleeps, which would hang indefinitely without a
    concurrent reader — proving the drainer's background thread is what actually unblocks it, not just that
    the code runs without raising."""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys\nfor _ in range(4000):\n    sys.stdout.write('x' * 50)\nsys.stdout.flush()",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    drainer = _OutputDrainer(process)
    drainer.start()
    try:
        # If the drainer weren't running, this wait() would hang past its timeout — the child would be
        # blocked writing into a full pipe, unable to ever reach exit. With the drainer running concurrently,
        # the child's writes are consumed as it goes, and it exits promptly.
        exit_code = process.wait(timeout=10.0)
        assert exit_code == 0
        assert len(drainer.output()) >= 200_000
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
