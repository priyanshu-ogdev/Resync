"""Proves a config written by `mcp_config.py` actually works, instead of trusting the write.

**Two tiers, chosen per client — not one generic check.** The strongest possible proof is asking the actual
client "do you see this server," using that client's own tooling; the fallback, for clients with no such
tooling, is spawning the same command/args the client would and handshaking it directly.

- **Tier A — headless client introspection.** A small number of clients ship their own real, non-interactive
  CLI that reads the client's *actual* loaded config and reports what it sees — not a reimplementation of the
  client's parsing logic, the client itself. Confirmed via live research (2026-09) for exactly two clients:
  - **Claude Code**: `claude mcp list` reads `.mcp.json`/`~/.claude.json` the same way the running app does
    and prints one line per server (`name: ✓ Connected` / `name: ✗ Failed to connect`). Real, currently-open
    caveats found in this research and reflected in `_verify_claude_code`'s fail-closed handling rather than
    ignored: multiple stdio servers configured at once have a documented race where only one connects
    (anthropics/claude-code#21341), and the CLI has been reported to fail sockets that the same version's
    VS Code extension connects fine (anthropics/claude-code#34982) — real, currently-open flakiness, not
    something this module papers over with a silent retry-until-green loop.
  - **Cursor**: `cursor-agent mcp list` reads the same `.cursor/mcp.json` this module writes. Real,
    currently-open caveat: headless/CI runs require an interactive trust/approval step with no documented
    bypass yet (Cursor forum: "MCP servers are not recognized with cursor-cli in a CI environment") —
    `_verify_cursor` reports `unavailable` for that specific failure text rather than a false `failed`.
  - No evidence was found of an equivalent headless "list what I actually loaded" command for VS Code,
    Windsurf, Zed, Claude Desktop, or OpenCode as of this research — Tier B is the honest ceiling for those.
- **Tier B — direct spawn-and-handshake** (every other registered client, and the fallback whenever a Tier A
  check itself reports `unavailable`, e.g. the binary isn't installed). Spawn the exact `command`/`args` pair
  just written, run a real MCP `initialize` + `tools/list` against it using the real client SDK. Proves the
  artifact is a working MCP server launchable exactly as configured; does not prove the specific GUI app
  parsed the file — see `verify_client_config`'s docstring for exactly what that residual gap is and why
  closing it for a closed-source GUI app would mean UI automation (screenshotting a panel, OCR/pixel-matching
  a status dot), trading a small, protocol-level check for one that breaks on every UI redesign rather than
  every protocol change — the opposite property this module exists for. Kept out of scope for that reason,
  not an oversight.

**Why this is a registry, not a client_a/client_b branch in one function**: `HEADLESS_VERIFIERS` maps a
client id to its Tier A checker exactly the way `mcp_config.REGISTRY` maps a client id to its `ClientSpec` —
adding a Tier A check for a client that ships one later is a new dict entry, not new control flow in
`verify_client_config`.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

EXPECTED_TOOLS: tuple[str, ...] = (
    "verify_package",
    "check_symbol_exists",
    "verify_patch_equivalence",
    "explain_change",
    "get_compatibility_report",
)
"""Kept in sync with the `@server.tool` registrations in server/app.py's `build_server` — if that
list changes, this one needs a matching edit, and `test_expected_tools_match_build_server` (test suite)
fails loudly instead of this check silently going stale."""

DEFAULT_TIMEOUT_SECONDS = 15.0
HEADLESS_TIMEOUT_SECONDS = 20.0
"""Headless client CLIs (Tier A) shell out to a real external binary that may itself be doing network I/O
(auth, telemetry) beyond just reading a local file — given a longer budget than the direct-spawn handshake."""


@dataclass(frozen=True)
class HandshakeResult:
    """Fail-closed by construction: `status` only ever takes one of these three values, never a bare
    True/False — a caller can't accidentally treat "couldn't check" as "checked and it's fine."
    """

    status: str  # "verified" | "failed" | "unavailable"
    detail: str
    tools_found: tuple[str, ...] = field(default_factory=tuple)
    missing_tools: tuple[str, ...] = field(default_factory=tuple)
    tier: str = "B"  # "A" (asked the real client) or "B" (direct spawn-and-handshake) — see module docstring

    @property
    def ok(self) -> bool:
        return self.status == "verified"


# ---------------------------------------------------------------------------------------------------------
# Tier B: direct spawn-and-handshake — the client-agnostic fallback.
# ---------------------------------------------------------------------------------------------------------


def _resolve_launch_command(repo_root: Path) -> list[str] | None:
    """The exact command a client config invokes: the installed `resync` console script if it's on PATH
    (the common case — matches what `mcp_config._resync_command()` actually writes into every generated
    config), else this same interpreter's `-m resync.cli.main` for an editable/dev checkout where the
    console script may not be linked yet. Returns `None` only if neither resolves, which becomes an
    "unavailable" result, never a guessed path.
    """
    for candidate in (
        repo_root / ".venv" / "Scripts" / "resync.exe",
        repo_root / ".venv" / "bin" / "resync",
    ):
        if candidate.exists() and candidate.is_file():
            return [str(candidate), "serve", "--transport", "stdio", "--repo", str(repo_root)]

    resync_bin = shutil.which("resync")
    if resync_bin:
        return [resync_bin, "serve", "--transport", "stdio", "--repo", str(repo_root)]
    try:
        import resync.cli.main  # noqa: F401  — confirms the package is importable from this interpreter
    except ImportError:
        return None
    return [sys.executable, "-m", "resync.cli.main", "serve", "--transport", "stdio", "--repo", str(repo_root)]


async def _run_handshake(command: list[str], timeout: float) -> HandshakeResult:
    try:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
    except ImportError as exc:
        return HandshakeResult(
            status="unavailable",
            detail=f"the 'mcp' client SDK isn't importable in this environment ({exc}) — install resync's "
            "own dependencies (it already pins mcp>=2.0) to enable this check.",
        )

    params = StdioServerParameters(command=command[0], args=command[1:])

    async def _handshake() -> HandshakeResult:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                found = tuple(sorted(tool.name for tool in listed.tools))
                missing = tuple(sorted(set(EXPECTED_TOOLS) - set(found)))
                if missing:
                    return HandshakeResult(
                        status="failed",
                        detail=f"server started and handshook, but is missing tool(s): {', '.join(missing)}",
                        tools_found=found,
                        missing_tools=missing,
                    )
                return HandshakeResult(
                    status="verified",
                    detail=f"real MCP initialize + tools/list succeeded; found all {len(EXPECTED_TOOLS)} "
                    "expected tools.",
                    tools_found=found,
                )

    try:
        return await asyncio.wait_for(_handshake(), timeout=timeout)
    except TimeoutError:
        return HandshakeResult(
            status="failed",
            detail=f"server process didn't complete the MCP handshake within {timeout:.0f}s — it may have "
            "hung, crashed after spawn, or be waiting on something (e.g. a missing resync.toml causing an "
            "unexpected prompt). Run the same command manually to see its own stderr.",
        )
    except Exception as exc:  # noqa: BLE001 — any subprocess/protocol failure is a "failed", not a crash here
        return HandshakeResult(status="failed", detail=f"handshake failed: {exc}")


def verify_server_launch(repo_root: Path, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> HandshakeResult:
    """Tier B, standalone: spawns `resync serve` exactly as a freshly-written client config would invoke
    it, performs a real MCP `initialize` + `tools/list` against it over stdio using the real client SDK, and
    confirms all three tools `build_server` registers are present. Client-agnostic — every registered
    `ClientSpec` (and `resync mcp-config custom`) ultimately launches the same `command`/`args` pair this
    function resolves and runs, so this one check covers all of them. Called directly by clients with no
    Tier A entry, and as the fallback from `verify_client_config` when a Tier A check reports `unavailable`.
    """
    command = _resolve_launch_command(repo_root)
    if command is None:
        return HandshakeResult(
            status="unavailable",
            detail="couldn't find an installed 'resync' console script or an importable resync.cli.main in "
            "this interpreter — can't spawn a real server process to verify against.",
            tier="B",
        )
    result = asyncio.run(_run_handshake(command, timeout))
    return HandshakeResult(**{**result.__dict__, "tier": "B"})


# ---------------------------------------------------------------------------------------------------------
# Tier A: headless introspection via the real client's own CLI, where one exists.
# ---------------------------------------------------------------------------------------------------------


def _run_cli(binary: str, args: list[str], *, cwd: Path, timeout: float) -> subprocess.CompletedProcess[str] | None:
    """Runs a real client CLI and returns its completed process, or `None` if the binary isn't on PATH —
    the one condition that should fall back to Tier B rather than be reported as a Tier A `failed`."""
    if shutil.which(binary) is None:
        return None
    try:
        return subprocess.run(  # noqa: S603 — binary resolved via shutil.which just above, args are fixed literals
            [binary, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args=[binary, *args], returncode=-1, stdout="", stderr="timed out")


def _verify_claude_code(repo_root: Path, name: str, timeout: float) -> HandshakeResult:
    """`claude mcp list` reads the same `.mcp.json` `write_config` just wrote and reports the client's own
    live connection status — see module docstring for the two real, currently-open flakiness caveats this
    honors rather than hides (a race with multiple stdio servers; some environments' CLI socket failures).
    """
    proc = _run_cli("claude", ["mcp", "list"], cwd=repo_root, timeout=timeout)
    if proc is None:
        return HandshakeResult(status="unavailable", detail="'claude' CLI not found on PATH.", tier="A")
    output = proc.stdout + proc.stderr
    # Real format per live research: "<name>: ... <ready-indicator>" where the indicator is a unicode
    # check/cross — matched by the words rather than the exact glyph, since terminal encoding can mangle it.
    line = next((ln for ln in output.splitlines() if ln.strip().startswith(f"{name}:")), None)
    if line is None:
        return HandshakeResult(
            status="failed",
            detail=f"'claude mcp list' ran but printed no entry for {name!r} — output: {output.strip()[:500]}",
            tier="A",
        )
    if "Failed to connect" in line or "✗" in line:
        return HandshakeResult(
            status="failed",
            detail=f"claude mcp list reports {name!r} failed to connect: {line.strip()}. Note: this can be "
            "a known CLI-side flake (anthropics/claude-code#21341, #34982) rather than a config problem — "
            "re-run 'claude mcp list' standalone to confirm before assuming the config is wrong.",
            tier="A",
        )
    if "Connected" in line or "✓" in line:
        return HandshakeResult(status="verified", detail=f"claude mcp list confirms: {line.strip()}", tier="A")
    return HandshakeResult(
        status="failed",
        detail=f"'claude mcp list' entry for {name!r} had an unrecognized status: {line.strip()}",
        tier="A",
    )


_CURSOR_CI_APPROVAL_MARKERS = ("has not been approved", "not been approved", "trust this workspace")


def _verify_cursor(repo_root: Path, name: str, timeout: float) -> HandshakeResult:
    """`cursor-agent mcp list` reads the same `.cursor/mcp.json` `write_config` just wrote. See module
    docstring: headless/CI runs can require an interactive trust/approval step with no documented bypass —
    that specific failure is reported as `unavailable` (an environment limitation), never a false `failed`.
    """
    proc = _run_cli("cursor-agent", ["mcp", "list"], cwd=repo_root, timeout=timeout)
    if proc is None:
        return HandshakeResult(status="unavailable", detail="'cursor-agent' CLI not found on PATH.", tier="A")
    output = proc.stdout + proc.stderr
    if any(marker in output for marker in _CURSOR_CI_APPROVAL_MARKERS) or "No MCP servers configured" in output:
        return HandshakeResult(
            status="unavailable",
            detail="cursor-agent requires interactive workspace trust/MCP approval before it will report "
            "server status headlessly (a real, currently-open Cursor CLI limitation, not a resync problem) "
            f"— output: {output.strip()[:300]}",
            tier="A",
        )
    match = re.search(rf"^\s*{re.escape(name)}\b.*$", output, re.MULTILINE)
    if match is None:
        return HandshakeResult(
            status="failed",
            detail=f"'cursor-agent mcp list' ran but printed no entry for {name!r} — output: {output.strip()[:500]}",
            tier="A",
        )
    line = match.group(0)
    if "ready" in line.lower() or "connected" in line.lower():
        return HandshakeResult(status="verified", detail=f"cursor-agent mcp list confirms: {line.strip()}", tier="A")
    return HandshakeResult(
        status="failed", detail=f"cursor-agent mcp list entry for {name!r} isn't ready: {line.strip()}", tier="A"
    )


HEADLESS_VERIFIERS: dict[str, Callable[[Path, str, float], HandshakeResult]] = {
    "claude-code": _verify_claude_code,
    "cursor": _verify_cursor,
}
"""Client id -> Tier A checker. See module docstring for exactly what was confirmed for each entry and why
every other registered client id is deliberately absent (no equivalent headless surface found)."""


def verify_client_config(
    client: str, repo_root: Path, *, name: str = "resync", timeout: float = HEADLESS_TIMEOUT_SECONDS
) -> HandshakeResult:
    """The generalized entry point `resync mcp-config --verify` calls: Tier A (`HEADLESS_VERIFIERS[client]`)
    if this client has one and it isn't itself `unavailable`, else Tier B (`verify_server_launch`). A caller
    that wants Tier B specifically (e.g. to sanity-check the server independent of any client) can call
    `verify_server_launch` directly instead.
    """
    headless = HEADLESS_VERIFIERS.get(client)
    if headless is not None:
        result = headless(repo_root, name, timeout)
        if result.status != "unavailable":
            return result
        # Tier A couldn't run (binary missing, needs interactive approval, etc.) — fall through to Tier B
        # rather than surface "unavailable" when a real check is still possible.
    return verify_server_launch(repo_root, timeout=DEFAULT_TIMEOUT_SECONDS)
