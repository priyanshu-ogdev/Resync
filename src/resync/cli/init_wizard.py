"""`resync init` — the interactive setup wizard (Phase 7).

Deliberately the one command in this CLI designed to be interactive by default. `docs/ui-design.md`'s
Surface 1 covers rich *output* (tables, color, progress indicators) for `check`/`sync`/`resolve`/`serve`,
which stay pure, scriptable, non-interactive commands — a CI pipeline or another program can invoke them
without a human at the keyboard, and that property must never regress. `init` is different by design:
onboarding is a one-time, human-present moment, the first thing a new user actually experiences, and
investing in a genuinely guided, well-designed terminal experience here is worth it precisely because it
happens rarely rather than on every invocation.

A `--yes`/non-interactive escape hatch still exists (`init --yes`, accepting every default) so this command
itself stays automatable for scripted setup (e.g. a devcontainer's postCreate step) even though its default
mode is conversational — the interactive design is a UX choice for the common case, not a hard requirement
that would make this command unusable in automation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import tomli_w
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from resync.config.schema import ConfidenceConfig, Pin, ProjectConfig, ResyncConfig, ScheduleConfig

_MODE_CHOICES = ["realtime", "scheduled", "hybrid"]
_PROFILE_CHOICES = ["latest", "pinned", "security-only"]


def run_init_wizard(repo_root: Path, console: Console, *, non_interactive: bool = False) -> Path:
    """Walks through setup and writes `resync.toml`. Returns the path written, for the caller to report or
    test against. Raises `FileExistsError` if a `resync.toml` already exists and the user (or
    `non_interactive` mode) doesn't confirm overwriting it — never silently clobbers existing config.
    """
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]resync[/bold cyan] — an AI-native compatibility engine for dependencies, APIs, "
            "and the agents that write your code.\n\n"
            "[dim]This wizard sets up resync.toml for this repo. It takes about a minute.[/dim]",
            border_style="cyan",
        )
    )

    config_path = repo_root / "resync.toml"
    if config_path.exists():
        overwrite = (
            True
            if non_interactive
            else Confirm.ask(
                f"[yellow]{config_path} already exists.[/yellow] Overwrite it?", default=False, console=console
            )
        )
        if not overwrite:
            raise FileExistsError(f"{config_path} already exists and was not overwritten")

    console.print("\n[bold]Project mode[/bold] — how aggressively should resync act on changes it finds?")
    console.print("  [cyan]realtime[/cyan]   block agents on known-bad calls as they write them")
    console.print("  [cyan]scheduled[/cyan]  batch corrections on a cadence, never mid-edit")
    console.print("  [cyan]hybrid[/cyan]     both — the recommended default")
    mode = "hybrid" if non_interactive else Prompt.ask("Mode", choices=_MODE_CHOICES, default="hybrid", console=console)

    target_profile = (
        "pinned"
        if non_interactive
        else Prompt.ask(
            "\n[bold]Target profile[/bold] — which versions should resync treat as the goal?",
            choices=_PROFILE_CHOICES,
            default="pinned",
            console=console,
        )
    )

    auto_apply_above = 0.95
    if not non_interactive:
        console.print(
            "\n[bold]Auto-apply threshold[/bold] — mechanical fixes at or above this confidence apply "
            "without asking; below it, they're proposed for review instead."
        )
        raw = Prompt.ask("Threshold (0.0-1.0)", default="0.95", console=console)
        try:
            auto_apply_above = max(0.0, min(1.0, float(raw)))
        except ValueError:
            console.print(f"[yellow]Couldn't parse {raw!r} as a number — using the default 0.95.[/yellow]")

    pins: list[Pin] = []
    if not non_interactive and Confirm.ask(
        "\n[bold]Pin any packages[/bold] resync should never propose upgrading past?",
        default=False,
        console=console,
    ):
        while True:
            package = Prompt.ask("  Package name", console=console)
            max_version = Prompt.ask("  Max version", console=console)
            reason = Prompt.ask("  Reason", default="pinned during setup", console=console)
            pins.append(Pin(package=package, max_version=max_version, reason=reason))
            if not Confirm.ask("  Add another pin?", default=False, console=console):
                break

    config = ResyncConfig(
        project=ProjectConfig(
            mode=cast(Literal["realtime", "scheduled", "hybrid"], mode), target_profile=target_profile
        ),
        schedule=ScheduleConfig(),
        confidence=ConfidenceConfig(auto_apply_above=auto_apply_above),
        pin=pins,
    )

    with config_path.open("wb") as f:
        tomli_w.dump(config.model_dump(mode="json"), f)

    _print_summary(config, config_path, console)
    return config_path


def _print_summary(config: ResyncConfig, config_path: Path, console: Console) -> None:
    table = Table(title="resync.toml written", show_header=False, border_style="green")
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Location", str(config_path))
    table.add_row("Mode", config.project.mode)
    table.add_row("Target profile", config.project.target_profile)
    table.add_row("Auto-apply threshold", f"{config.confidence.auto_apply_above:.2f}")
    table.add_row("Pins", str(len(config.pin)) if config.pin else "none")
    console.print()
    console.print(table)

    console.print(
        Panel.fit(
            "[bold]Next steps[/bold]\n\n"
            "  [cyan]resync mcp-config claude-code[/cyan]   add resync to your coding agent (or opencode, "
            "cursor, vscode, windsurf, zed, antigravity, ...)\n"
            "  [cyan]resync sync --tier mechanical[/cyan]   preview known fixes against this repo\n"
            "  [cyan]resync check[/cyan]                    scan for anything already broken\n"
            "  [cyan]resync serve[/cyan]                    start the MCP server directly\n",
            border_style="dim",
        )
    )


def seed_knowledge_store(repo_root: Path, console: Console) -> int:
    """Optionally offered at the end of `init`: populate `.resync/knowledge.lancedb` with the built-in
    verified seed records (`knowledge/seed_data.py`) so `resync check`/`sync` have something to check
    against immediately, rather than an empty store. Returns the number of records seeded.
    """
    from resync.knowledge import store
    from resync.knowledge.seed_data import SEED_RECORDS

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        progress.add_task(description="Seeding knowledge store...", total=None)
        db_path = store.default_db_path(repo_root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = store.connect(db_path)
        table = store.get_or_create_table(db)
        store.upsert(table, SEED_RECORDS)

    console.print(f"[green]Seeded {len(SEED_RECORDS)} known changes into {store.default_db_path(repo_root)}[/green]")
    return len(SEED_RECORDS)
