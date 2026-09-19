"""Phase 6: `llama-server` process lifecycle management — start, health-check, stop.

Per `docs/tech-stack.md`, the coding model runs as its own OS process over an OpenAI-compatible HTTP
endpoint, never in-process with resync itself, so its memory footprint (the whole reason for the 6-12GB VRAM
budget this project is designed around) stays isolated from the knowledge server's. This module owns exactly
that process's lifecycle — starting it, waiting for it to actually be ready, and stopping it cleanly — and
nothing about what's said to it once it's up (that's `llm/generator.py` and `verification/critic.py`'s
concrete implementation).

**CLI flags and HTTP surface verified against current, real documentation before writing any code against
them** (this project's one standing convention — AGENTS.md), not assumed from general familiarity with
llama.cpp, which has changed its flags and endpoints repeatedly across versions:
- `llama-server -m <path.gguf> --host <host> --port <port> [--n-gpu-layers N] [--ctx-size N] [--alias name]`
- `GET /health` -> `{"status": "ok"}` once the model has finished loading (not merely once the process has
  started — a process can be running and accepting TCP connections well before the model is actually loaded
  into VRAM, which is exactly why a health *endpoint* exists rather than just checking `Popen.poll()`).
- `POST /v1/chat/completions` — OpenAI-compatible; this module doesn't call it, `generator.py`/`critic.py` do.

**Not exercised end-to-end in this development environment, honestly, not silently**: no network access here
to download either the `llama-server` binary or a real GGUF model file, so the "start a real process and see
it become healthy" path has not run for real — the same class of gap this project already documents for
`sandbox-runtime`, `griffe`, and `uv`'s live registry calls. What is tested here: argument construction
(the exact command line built from `LlamaServerConfig`, verified against the real, cited flag names above),
health-polling logic against a mocked HTTP layer, and — the one thing genuinely testable without the real
binary — that a nonexistent binary name raises the documented `LlamaServerUnavailableError` rather than a
raw `FileNotFoundError`, exactly the same real-binary-adjacent test pattern already used in
`resolve/resolver.py` and `verification/sandbox.py` for the same reason.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

_DEFAULT_HEALTH_TIMEOUT_SECONDS = 120.0
_HEALTH_POLL_INTERVAL_SECONDS = 0.5
_STOP_GRACE_PERIOD_SECONDS = 10.0


class LlamaServerUnavailableError(RuntimeError):
    """The `llama-server` binary isn't installed/on PATH, the model file doesn't exist, the process exited
    before becoming healthy, or it never became healthy within the timeout. Never conflated with a
    successfully-running server returning a bad *answer* — that's the caller's (generator/critic's) concern,
    this module only guarantees the process itself is up and responding to `/health`.
    """


class _OutputDrainer:
    """Continuously reads `process.stdout` on a background thread into an in-memory buffer.

    **A real, previously-undetected bug this exists to fix, found by review rather than by a failing test**:
    `start()` launches `llama-server` with `stdout=subprocess.PIPE, stderr=subprocess.STDOUT`, but nothing
    read from that pipe until *after* the process had already exited (the old code only called
    `process.stdout.read()` inside the "process died before becoming healthy" branch). An OS pipe has a
    small, fixed buffer (~64KB on Linux) — once a child process's combined stdout+stderr output fills it,
    the child's next `write()` call blocks until something reads the pipe. `llama-server` logs verbosely
    while loading a model (exactly the phase `_wait_until_healthy` is polling through), so a real run could
    genuinely fill that buffer, deadlock the child mid-startup, and time out for a completely misleading
    reason — "never became healthy" instead of the real cause, "blocked writing its own logs because nothing
    was reading them." No test caught this because every existing test uses a fake process that produces
    negligible output, never enough to fill a real pipe buffer.

    Draining on a background thread (started right after `Popen`, for the process's entire lifetime) is the
    standard fix for this exact class of subprocess deadlock — it both prevents the child from ever
    blocking on `write()`, and keeps the accumulated output available for error messages via `output()`,
    which is what `_wait_until_healthy`'s error paths now read from instead of a one-shot `.read()` that
    could itself block or return nothing once the pipe's already been drained by this thread.
    """

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self._chunks: list[bytes] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._drain, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _drain(self) -> None:
        stdout = self._process.stdout
        if stdout is None:
            return
        for chunk in iter(lambda: stdout.read(4096), b""):
            with self._lock:
                self._chunks.append(chunk)

    def output(self) -> str:
        with self._lock:
            return b"".join(self._chunks).decode(errors="replace")


@dataclass
class LlamaServerConfig:
    model_path: Path
    host: str = "127.0.0.1"
    port: int = 8080
    n_gpu_layers: int | None = None
    """None means "let llama-server decide" (its own default) rather than this module silently picking a
    number — a real value here should come from the caller's own VRAM-budget knowledge
    (docs/tech-stack.md's 6-12GB target), not a guess made in this module."""
    ctx_size: int | None = None
    alias: str | None = None
    extra_args: list[str] = field(default_factory=list)
    """Escape hatch for flags this module doesn't model explicitly — never silently dropped, always
    appended verbatim to the real command line."""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def to_argv(self, binary: str = "llama-server") -> list[str]:
        argv = [binary, "-m", str(self.model_path), "--host", self.host, "--port", str(self.port)]
        if self.n_gpu_layers is not None:
            argv += ["--n-gpu-layers", str(self.n_gpu_layers)]
        if self.ctx_size is not None:
            argv += ["--ctx-size", str(self.ctx_size)]
        if self.alias is not None:
            argv += ["--alias", self.alias]
        argv += self.extra_args
        return argv


@dataclass
class LlamaServerHandle:
    """What a caller actually needs once the server is confirmed healthy — the base URL to send requests to,
    and enough to stop the process later. Deliberately not the raw `subprocess.Popen` itself: callers should
    go through `stop()` below, not manage the process directly, so this module stays the one place that
    knows how to shut it down cleanly.
    """

    config: LlamaServerConfig
    process: subprocess.Popen[bytes]

    @property
    def base_url(self) -> str:
        return self.config.base_url


def start(
    config: LlamaServerConfig,
    *,
    binary: str = "llama-server",
    health_timeout: float = _DEFAULT_HEALTH_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> LlamaServerHandle:
    """Start `llama-server` and block until `/health` reports ready, or raise
    `LlamaServerUnavailableError`. `client` is injectable for the same reason `server/tools.py`'s
    `verify_package` makes its `httpx.Client` injectable — tests exercise the real polling loop against
    `httpx.MockTransport` rather than needing a real server.
    """
    if shutil.which(binary) is None:
        raise LlamaServerUnavailableError(
            f"'{binary}' is not on PATH. Install llama.cpp's server binary "
            "(https://github.com/ggml-org/llama.cpp) — resync does not bundle or download it."
        )
    if not config.model_path.exists():
        raise LlamaServerUnavailableError(f"model file not found: {config.model_path}")

    try:
        process = subprocess.Popen(  # noqa: S603 — binary presence just verified via shutil.which above
            config.to_argv(binary), stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
    except OSError as exc:
        raise LlamaServerUnavailableError(f"failed to start '{binary}': {exc}") from exc

    drainer = _OutputDrainer(process)
    drainer.start()

    owns_client = client is None
    http_client = client or httpx.Client(timeout=5.0)
    try:
        _wait_until_healthy(process, config.base_url, health_timeout, http_client, drainer)
    except LlamaServerUnavailableError:
        _terminate(process)
        raise
    finally:
        if owns_client:
            http_client.close()

    return LlamaServerHandle(config=config, process=process)


def _wait_until_healthy(
    process: subprocess.Popen[bytes], base_url: str, timeout: float, client: httpx.Client, drainer: _OutputDrainer
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise LlamaServerUnavailableError(
                f"llama-server exited with code {exit_code} before becoming healthy. Output: {drainer.output()[-2000:]}"
            )
        try:
            response = client.get(f"{base_url}/health")
            if response.status_code == 200 and response.json().get("status") == "ok":
                return
        except httpx.HTTPError:
            pass  # not up yet — expected during startup, keep polling rather than fail on the first try
        time.sleep(_HEALTH_POLL_INTERVAL_SECONDS)

    _terminate(process)
    raise LlamaServerUnavailableError(
        f"llama-server did not become healthy within {timeout}s. Output: {drainer.output()[-2000:]}"
    )


def stop(handle: LlamaServerHandle) -> None:
    """Stop the server cleanly: SIGTERM, then SIGKILL after a grace period if it hasn't exited — never leave
    a process (and the VRAM it's holding) orphaned."""
    _terminate(handle.process)


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return  # already exited
    process.terminate()
    try:
        process.wait(timeout=_STOP_GRACE_PERIOD_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
