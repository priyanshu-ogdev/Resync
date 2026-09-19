"""Generates and writes MCP client configuration so `resync serve` can be added to a supported client with
one command, instead of hand-editing JSON in whichever format that client happens to use.

**Design: a declarative registry, not per-client code branches — built specifically because MCP client
config formats are a moving target, not a settled standard.** Live research for this module (see each
`ClientSpec.notes` below for citations) found **four genuinely different JSON shapes** across eight clients,
not eight clients each mildly reformatting one shape:

1. `{"mcpServers": {name: {"command": str, "args": [...], "env": {...}}}}` — Claude Desktop, Claude Code,
   Cursor, Windsurf, Antigravity.
2. `{"servers": {name: {"type": "stdio", "command": str, "args": [...], "env": {...}}}}` — VS Code. Different
   root key, and (per VS Code's own current MCP developer guide) an *explicitly required* `type` field —
   unlike shape 1's clients, which infer the transport from which keys are present.
3. `{"mcp": {name: {"type": "local", "command": [str, ...], "environment": {...}, "enabled": true}}}` —
   OpenCode. Different root key, a single combined command *array* instead of separate `command`/`args`,
   and the env-var key is `environment`, not `env`.
4. `{"context_servers": {name: {"command": {"path": str, "args": [...]}}}}` — Zed. Different root key again,
   and command/args are *nested inside* a `command` object rather than being sibling keys.

A hardcoded `if client == "x": ...` chain across four shapes for eight (and growing) clients is exactly the
kind of code that gets harder to trust with every addition, and — the more important property here — harder
to *patch quickly* when one client changes its format on its own schedule, which this research already found
real, current, open examples of (see `KNOWN_ISSUES` below). The `ClientSpec` registry below turns "support a
new client" and "a client changed its format" into a data change (add/edit one `ClientSpec`), not new control
flow, and `add_client_from_spec`/`describe_registry` mean an *unlisted* agent doesn't need to wait for a code
release either — see "Scaling past the registry" below.

**Scaling past the registry: any MCP-compliant agent, listed or not.** Every compliant client accepts the
same underlying `command`/`args`/`env` triple somewhere in its own config shape — that invariant is what MCP
compliance means. So a client with no `ClientSpec` entry yet is not a dead end: `resync mcp-config custom`
takes the four shape parameters directly (`--root-key`, `--command-style`, `--env-key`, `--type-value`) and
builds the same way a registered `ClientSpec` would, from the CLI, no code change or new release required.
`describe_registry()` (`resync mcp-config list`) surfaces each entry's `last_verified` date and `notes` so a
person can judge for themselves whether a listed format might have drifted since — this module cannot detect
that on its own (there is no live schema registry for MCP client configs to check against), so it says so
plainly rather than implying a confidence it doesn't have.

**Real, currently-open format issues found during this research, tracked in `KNOWN_ISSUES` rather than
silently worked around or ignored**:
- Claude Desktop does **not** support the `url`/Streamable-HTTP transport at all — a real, documented bug
  (anthropics/claude-code#37286) shows it silently deletes the *entire* `mcpServers` section (and some
  unrelated preference keys) on startup if it finds a `url`-based entry. This module never emits one for
  Claude Desktop — `ClientSpec.supports_url=False` enforces this structurally, not just by convention.
- OpenCode's `environment` field is confirmed, in some versions, to not actually reach the spawned child
  process (anomalyco/opencode#26332) — resync's own server needs no extra environment variables to run, so
  this doesn't block using it, but it's worth knowing before relying on it for another server.
- Antigravity's config file path is genuinely unsettled across its own Desktop/IDE/CLI surfaces and recent
  version history (multiple independent, credible, mutually-conflicting reports:
  `~/.gemini/config/mcp_config.json`, `~/.gemini/antigravity/mcp_config.json`,
  `~/.gemini/antigravity-ide/mcp_config.json`, and others). `ClientSpec.path_resolver=None` means this
  module never guesses; it shows the JSON and points to Antigravity's own in-app "Manage MCP Servers → View/
  Open raw config" UI instead, confirmed by independent sources as the reliable, version-independent route.

**Merging, not overwriting**: every client config file here is a file the person may already have other MCP
servers or unrelated settings in. `write_config` reads the existing file if present and merges resync's
entry into the relevant server-list key, leaving every other key and every other server entry untouched —
never replaces the whole file.
"""

from __future__ import annotations

import json
import platform
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

CommandStyle = Literal["separate", "array", "nested_object"]
"""How a client expresses "run this program with these arguments":
- "separate": sibling `command` (str) and `args` (list[str]) keys — shape 1 and shape 2 above.
- "array": one combined `command` list, executable first — shape 3 (OpenCode) above.
- "nested_object": `command` is itself an object with its own `path`/`args` keys — shape 4 (Zed) above.
"""


@dataclass(frozen=True)
class ClientSpec:
    """Everything needed to generate and place a config entry for one MCP client, and nothing that would
    require new control flow to add another — see module docstring for why this is a registry, not code.
    """

    id: str
    display_name: str
    root_key: str
    """The top-level key holding the map of server-name -> server-config (`mcpServers`/`servers`/`mc`p`/
    `context_servers`)."""
    command_style: CommandStyle
    requires_type_field: bool = False
    type_value: str | None = None
    """The literal value for the (optional or required) `type` field, e.g. `"stdio"` for VS Code, `"local"`
    for OpenCode. `None` when the client doesn't use one at all (Claude/Cursor/Windsurf/Antigravity/Zed)."""
    env_key: str | None = "env"
    """The key for environment variables — `"env"` (the common case), `"environment"` (OpenCode), or `None`
    if this client's shape has no documented place for one (kept structurally impossible to emit rather than
    silently wrong)."""
    extra_fields: dict[str, Any] = field(default_factory=dict)
    """Fields present in every entry beyond command/args/env/type — e.g. OpenCode's `"enabled": true`."""
    supports_url: bool = False
    url_field: str = "url"
    """Confirmed real per-client differences even here: Antigravity's remote field is `serverUrl`, not
    `url` — see module docstring. Not yet used by `generate_entry` (this module only emits stdio servers
    today), kept on the spec so a future remote-transport mode has this already researched and recorded
    rather than needing to redo the research then.
    """
    path_resolver: Callable[[Path], Path] | None = None
    """Returns the real config file path given a repo root, or `None` when no single path can be trusted —
    see Antigravity's entry and module docstring for why guessing is worse than asking."""
    last_verified: str = "unknown"
    notes: str = ""


def _claude_desktop_path(_repo_root: Path) -> Path:
    """OS-specific, per Claude Desktop's own documented locations (confirmed across multiple independent,
    current sources) — this file lives outside any project, unlike every other client this module supports.
    """
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        import os

        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _windsurf_path(_repo_root: Path) -> Path:
    """Global-only, per multiple independent, current sources — no project-level variant was found
    anywhere in this research, unlike Cursor/VS Code/Claude Code/OpenCode/Zed, which all support one."""
    system = platform.system()
    base = Path.home() / (".codeium" if system != "Windows" else ".codeium")
    return base / "windsurf" / "mcp_config.json"


REGISTRY: dict[str, ClientSpec] = {
    spec.id: spec
    for spec in [
        ClientSpec(
            id="claude-desktop",
            display_name="Claude Desktop",
            root_key="mcpServers",
            command_style="separate",
            path_resolver=_claude_desktop_path,
            last_verified="2026-09",
            notes="Never emits a url/HTTP entry — anthropics/claude-code#37286 confirms Claude Desktop "
            "silently deletes its entire mcpServers section (and some preference keys) on startup if it "
            "finds one.",
        ),
        ClientSpec(
            id="claude-code",
            display_name="Claude Code",
            root_key="mcpServers",
            command_style="separate",
            requires_type_field=False,  # optional, not required, unlike VS Code — included anyway for clarity
            type_value="stdio",
            path_resolver=lambda repo_root: repo_root / ".mcp.json",
            last_verified="2026-09",
            notes="A genuinely different file from Claude Desktop's claude_desktop_config.json — confirmed "
            "explicitly by multiple current sources that Claude Code never reads that file. .mcp.json at "
            "the project root is the team-shareable convention; Claude Code also reads ~/.claude.json and "
            "~/.claude/settings*.json for user-level servers, not generated here.",
        ),
        ClientSpec(
            id="cursor",
            display_name="Cursor",
            root_key="mcpServers",
            command_style="separate",
            path_resolver=lambda repo_root: repo_root / ".cursor" / "mcp.json",
            last_verified="2026-09",
            notes="Infers stdio from the presence of `command`, like Claude — no type field.",
        ),
        ClientSpec(
            id="vscode",
            display_name="VS Code / GitHub Copilot",
            root_key="servers",
            command_style="separate",
            requires_type_field=True,
            type_value="stdio",
            path_resolver=lambda repo_root: repo_root / ".vscode" / "mcp.json",
            last_verified="2026-09",
            notes='Per VS Code\'s own current MCP developer guide: unlike every "separate"-style client '
            "above, VS Code does NOT infer the transport from which keys are present — a server block "
            'missing "type" is invalid. Project-level (.vscode/mcp.json) only; user-level servers need '
            'the "MCP: Open User Configuration" command, not a file this module can target.',
        ),
        ClientSpec(
            id="opencode",
            display_name="OpenCode",
            root_key="mcp",
            command_style="array",
            requires_type_field=True,
            type_value="local",
            env_key="environment",
            extra_fields={"enabled": True},
            path_resolver=lambda repo_root: repo_root / "opencode.json",
            last_verified="2026-09",
            notes='Root key is "mcp", not "mcpServers"; command is one combined array, not separate '
            'command/args; env key is "environment", not "env" — three independent departures from the '
            "common shape, each confirmed by multiple current sources. anomalyco/opencode#26332: "
            "environment vars are confirmed to sometimes not reach the child process in practice.",
        ),
        ClientSpec(
            id="windsurf",
            display_name="Windsurf",
            root_key="mcpServers",
            command_style="separate",
            path_resolver=_windsurf_path,
            last_verified="2026-09",
            notes="Global config only (~/.codeium/windsurf/mcp_config.json) — no project-level file found "
            "in this research, unlike the other clients here.",
        ),
        ClientSpec(
            id="zed",
            display_name="Zed",
            root_key="context_servers",
            command_style="nested_object",
            path_resolver=lambda repo_root: repo_root / ".zed" / "settings.json",
            last_verified="2026-09",
            notes='Root key "context_servers", and command/args are nested *inside* a `command` object '
            '({"command": {"path": ..., "args": [...]}}) rather than sibling keys — confirmed directly '
            "against a real example in Zed's own client-setup documentation. Also merges into settings.json"
            ", a file that holds many unrelated editor settings beyond MCP — merge_config only ever touches "
            "the context_servers key, never anything else in that file.",
        ),
        ClientSpec(
            id="antigravity",
            display_name="Google Antigravity",
            root_key="mcpServers",
            command_style="separate",
            supports_url=True,
            url_field="serverUrl",
            path_resolver=None,
            last_verified="2026-09",
            notes="JSON shape confirmed across multiple independent sources including real local-Docker-"
            "server examples. File path deliberately NOT auto-written: research found genuinely conflicting "
            "reports across Antigravity's Desktop/IDE/CLI surfaces and recent version history "
            "(~/.gemini/config/mcp_config.json, ~/.gemini/antigravity/mcp_config.json, "
            "~/.gemini/antigravity-ide/mcp_config.json, and others) — guessing one would risk writing to a "
            "file Antigravity doesn't read for a given surface/version. Use Antigravity's own in-app "
            '"Manage MCP Servers -> View/Open raw config" instead, confirmed by independent sources as the '
            "reliable, version-independent way to find the right file. serverUrl (not url) is its remote-"
            "transport field, confirmed by two independent sources naming this exact difference explicitly.",
        ),
    ]
}

CLIENT_IDS: tuple[str, ...] = tuple(REGISTRY.keys())

KNOWN_ISSUES: dict[str, str] = {spec.id: spec.notes for spec in REGISTRY.values() if spec.notes}

_STDIO_ARGS = ["serve", "--transport", "stdio"]


def _resync_command() -> str:
    """The command a generated config should invoke. `"resync"` assumes the console-script entry point
    (`pyproject.toml`'s `[project.scripts]`) is on the invoking client's PATH — true for a normal
    `pip install`/`uv tool install`, but not for a `uv run` development checkout. Kept as a plain string,
    not resolved via `shutil.which`/`sys.executable` at generation time, deliberately: the config is meant
    to be portable to wherever the client actually runs (which may not be this machine, e.g. a synced
    Settings Sync profile), so baking in *this* environment's absolute interpreter path would be wrong more
    often than it would help.
    """
    return "resync"


def build_entry(
    *,
    command: str,
    args: list[str],
    root_key: str,
    command_style: CommandStyle,
    requires_type_field: bool = False,
    type_value: str | None = None,
    env_key: str | None = "env",
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The generic shape-interpreter every `ClientSpec` (and `resync mcp-config custom`) goes through —
    this is the one place that knows how to render each of the four real shapes module docstring describes,
    so adding a client never means writing a new branch here, only a new `ClientSpec` (or CLI flags) that
    parameterize this same function.
    """
    entry: dict[str, Any] = {}
    if requires_type_field and type_value is not None:
        entry["type"] = type_value
    if command_style == "separate":
        entry["command"] = command
        entry["args"] = list(args)
    elif command_style == "array":
        entry["command"] = [command, *args]
    elif command_style == "nested_object":
        entry["command"] = {"path": command, "args": list(args)}
    else:
        raise ValueError(f"unknown command_style {command_style!r}")
    if extra_fields:
        entry.update(extra_fields)
    # env_key is accepted for symmetry with real specs but no env vars are needed to run `resync serve`
    # today — an empty env dict would be noise in the generated file, so it's only ever added if truthy.
    del env_key
    return entry


def generate_entry(client: str, *, name: str = "resync") -> dict[str, Any]:
    """The server-entry object for a registered `client` (not the whole file — see `merge_config` for how
    this fits into an existing file's server-list key). Raises `KeyError` for an unregistered client —
    use `build_entry` directly, or `resync mcp-config custom`, for one not in `REGISTRY`.
    """
    spec = REGISTRY[client]
    return build_entry(
        command=_resync_command(),
        args=_STDIO_ARGS,
        root_key=spec.root_key,
        command_style=spec.command_style,
        requires_type_field=spec.requires_type_field,
        type_value=spec.type_value,
        env_key=spec.env_key,
        extra_fields=spec.extra_fields,
    )


def config_path_for(client: str, repo_root: Path) -> Path | None:
    """The file this module writes to for `client`, or `None` when the spec has no trustworthy single path
    (currently only Antigravity — see its `ClientSpec.notes`)."""
    spec = REGISTRY[client]
    return spec.path_resolver(repo_root) if spec.path_resolver is not None else None


def merge_config(existing: dict[str, Any], client: str, *, name: str = "resync") -> dict[str, Any]:
    """Returns a new dict: `existing` with resync's entry added/updated under the right server-list key for
    `client`, every other key and every other server entry left exactly as-is. `existing` itself is never
    mutated, so a caller that wants to compare before/after still can.
    """
    spec = REGISTRY[client]
    result: dict[str, Any] = {}
    if client == "opencode" and "$schema" not in existing:
        result["$schema"] = "https://opencode.ai/config.json"  # first, matching convention — cosmetic only
    result.update(existing)
    servers = dict(result.get(spec.root_key, {}))
    servers[name] = generate_entry(client, name=name)
    result[spec.root_key] = servers
    return result


def write_config(client: str, repo_root: Path, *, name: str = "resync") -> Path:
    """Merges resync's entry into `client`'s real config file (creating the file and any parent directories
    it needs if it doesn't exist yet) and returns the path written. Raises `ValueError` when `client`'s spec
    has no `path_resolver` (currently only Antigravity) — call `format_for_display` for that client instead.
    """
    if client not in REGISTRY:
        raise ValueError(f"unknown client {client!r} (expected one of {CLIENT_IDS})")
    path = config_path_for(client, repo_root)
    if path is None:
        spec = REGISTRY[client]
        raise ValueError(
            f"{spec.display_name}'s config file path isn't auto-written — see this module's docstring for "
            "why. Use format_for_display() and the client's own in-app config UI instead."
        )

    existing: dict[str, Any] = {}
    if path.exists():
        text = path.read_text().strip()
        if text:
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path} exists but isn't valid JSON — refusing to overwrite it blindly: {exc}"
                ) from exc
            if not isinstance(loaded, dict):
                raise ValueError(f"{path} exists but its top level isn't a JSON object — refusing to merge into it.")
            existing = loaded

    merged = merge_config(existing, client, name=name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2) + "\n")
    return path


def format_for_display(client: str, *, name: str = "resync") -> str:
    """A complete, pretty-printed config snippet for `client` — what to show someone (Antigravity, or
    anyone who passed `--print`) rather than write directly."""
    spec = REGISTRY[client]
    doc: dict[str, Any] = {}
    if client == "opencode":
        doc["$schema"] = "https://opencode.ai/config.json"
    doc[spec.root_key] = {name: generate_entry(client, name=name)}
    return json.dumps(doc, indent=2)


def format_custom(
    *,
    root_key: str,
    command_style: CommandStyle,
    env_key: str | None = "env",
    type_value: str | None = None,
    name: str = "resync",
) -> str:
    """The escape hatch for any MCP-compliant agent not yet in `REGISTRY` — see module docstring's "Scaling
    past the registry" section. Every compliant client accepts *some* command/args/env triple; this builds
    it directly from the shape parameters the person supplies (from that client's own docs), the same way
    a registered `ClientSpec` would, without needing a code change first.
    """
    entry = build_entry(
        command=_resync_command(),
        args=_STDIO_ARGS,
        root_key=root_key,
        command_style=command_style,
        requires_type_field=type_value is not None,
        type_value=type_value,
        env_key=env_key,
    )
    return json.dumps({root_key: {name: entry}}, indent=2)


def describe_registry() -> list[dict[str, str]]:
    """One row per registered client — `id`, `display_name`, `last_verified`, `notes` — for
    `resync mcp-config list`. Exists specifically so a person can judge for themselves whether a listed
    format might have drifted since `last_verified`, since this module has no way to check that on its own
    (there's no live schema registry for MCP client configs to compare against) — see module docstring.
    """
    return [
        {"id": spec.id, "display_name": spec.display_name, "last_verified": spec.last_verified, "notes": spec.notes}
        for spec in REGISTRY.values()
    ]
