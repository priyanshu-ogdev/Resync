"""Resync's CLI entry point.

See docs/architecture.md#integration-surfaces. This is the offline-first surface: a developer running
Resync locally against the 6-12GB VRAM local model, without the GitHub App or a remote MCP deployment.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from rich.console import Console

    from resync.config.schema import ResyncConfig
    from resync.knowledge.schema import KnowledgeRecord

app = typer.Typer(help="An AI-native compatibility engine for dependencies, APIs, and the agents that write your code.")


@app.command()
def init(
    repo: Path = typer.Argument(Path("."), help="Repo to set up resync.toml for"),
    yes: bool = typer.Option(
        False, "--yes", help="Accept every default non-interactively (for scripted setup, e.g. a devcontainer)."
    ),
    seed: bool | None = typer.Option(
        None,
        "--seed/--no-seed",
        help="Seed the knowledge store with resync's built-in verified records. Omit to be asked "
        "interactively (or to default to yes under --yes).",
    ),
) -> None:
    """Interactive setup wizard — writes resync.toml for this repo.

    The one command in this CLI designed to be conversational by default (see `cli/init_wizard.py`'s module
    docstring for why): onboarding is a one-time, human-present moment, unlike `check`/`sync`/`resolve`/
    `serve`, which stay pure and scriptable so CI or another program can invoke them without a human in the
    loop. `--yes` keeps this command itself automatable when that's what's actually needed.
    """
    from rich.console import Console

    from resync.cli.init_wizard import run_init_wizard, seed_knowledge_store

    console = Console()
    repo_root = repo.resolve()
    try:
        run_init_wizard(repo_root, console, non_interactive=yes)
    except FileExistsError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=0) from None

    should_seed = seed if seed is not None else (True if yes else _confirm_seed(console))
    if should_seed:
        seed_knowledge_store(repo_root, console)


def _confirm_seed(console: Console) -> bool:
    from rich.prompt import Confirm

    return Confirm.ask(
        "\nSeed the knowledge store with resync's built-in verified records now?", default=True, console=console
    )


@app.command()
def serve(
    transport: str = typer.Option("stdio", help="stdio | http — see docs/adr/0001-mcp-client-server-split.md"),
    port: int = typer.Option(8787, help="Only used when --transport http"),
    repo: Path | None = typer.Option(
        None, help="Repo this server checks. Defaults to $RESYNC_REPO_ROOT, else the current directory."
    ),
) -> None:
    """Start the MCP server (local stdio process, or Streamable HTTP for team/remote use)."""
    from resync.server.app import run as run_server

    run_server(transport, repo_root=repo, port=port)


@app.command()
def resolve(
    requirements: list[str] = typer.Argument(..., help="PEP 508 requirement strings, e.g. 'transformers>=4.30'"),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo whose resync.toml pins constrain the resolve"),
) -> None:
    """Resolve requirements via `uv` (honoring resync.toml pins), then run the supply-chain provenance gate
    on every resolved version before reporting it — docs/architecture.md#supply-chain-provenance-gate:
    "before landing any resolved version... check it against OSV.dev... and where available its Sigstore
    signature." OSV/advisory coverage is `resync check`'s job (via verify_package); this command's job is
    resolving new candidate versions in the first place and gating them on provenance before they're
    reported as safe to add.
    """
    import typer as _typer
    from rich.console import Console
    from rich.table import Table

    from resync.adapters.python.resolver import ResolverError, ResolverUnavailableError
    from resync.adapters.python.resolver import resolve as run_resolve
    from resync.verification.provenance import ProvenanceOutcome, check_provenance

    console = Console()
    repo_root = repo.resolve()

    try:
        result = run_resolve(requirements, repo_root)
    except ResolverUnavailableError as exc:
        console.print(f"[yellow]Resolver unavailable:[/yellow] {exc}")
        raise _typer.Exit(code=2) from exc
    except ResolverError as exc:
        console.print(f"[red]Resolution failed:[/red] {exc}")
        raise _typer.Exit(code=1) from exc

    table = Table(title=f"Resolved {len(result.dependencies)} package(s)")
    table.add_column("Package")
    table.add_column("Version")
    table.add_column("Provenance")
    table.add_column("Detail")

    any_invalid = False
    for dep in result.dependencies:
        prov = check_provenance(dep.name, dep.version)
        if prov.outcome == ProvenanceOutcome.INVALID:
            any_invalid = True
        style = {
            ProvenanceOutcome.VERIFIED: "green",
            ProvenanceOutcome.NO_ATTESTATION: "white",
            ProvenanceOutcome.CHECK_UNAVAILABLE: "yellow",
            ProvenanceOutcome.INVALID: "bold red",
        }[prov.outcome]
        detail = prov.files[0].detail if prov.files else ""
        table.add_row(dep.name, dep.version, f"[{style}]{prov.outcome.value}[/{style}]", detail)

    console.print(table)
    if any_invalid:
        console.print(
            "[bold red]At least one resolved package failed provenance verification.[/bold red] Do not "
            "land this resolution without manual review."
        )
        raise _typer.Exit(code=1)


@app.command()
def check(
    repo: Path = typer.Argument(Path("."), help="Repo to run the real-time verification sweep against"),
) -> None:
    """Run the fast verification checks (verify_package / check_symbol_exists) against an existing repo,
    without going through an agent's MCP call — useful as a pre-commit or CI step."""
    import typer as _typer
    from rich.console import Console
    from rich.table import Table

    from resync.cli.scan import is_actionable, run_dependency_checks, run_symbol_checks

    repo_root = repo.resolve()
    console = Console()

    console.print(f"[bold]Scanning {repo_root}[/bold]")
    dep_findings = run_dependency_checks(repo_root)
    symbol_findings = run_symbol_checks(repo_root)

    actionable_deps = [f for f in dep_findings if is_actionable(f.result.outcome)]
    actionable_symbols = [f for f in symbol_findings if f.result is not None and is_actionable(f.result.outcome)]
    unresolved_symbols = [f for f in symbol_findings if f.result is None]

    if actionable_deps:
        table = Table(title="Dependency issues")
        table.add_column("Package")
        table.add_column("Outcome")
        table.add_column("Detail")
        for f in actionable_deps:
            table.add_row(f.package, f.result.outcome.value, f.result.detail)
        console.print(table)
    else:
        console.print(f"[green]No dependency issues[/green] ({len(dep_findings)} checked)")

    if actionable_symbols:
        table = Table(title="Symbol issues")
        table.add_column("Symbol")
        table.add_column("Outcome")
        table.add_column("Detail")
        table.add_column("Files")
        for sf in actionable_symbols:
            files = ", ".join(str(p.relative_to(repo_root)) for p in sf.files[:3])
            if len(sf.files) > 3:
                files += f" (+{len(sf.files) - 3} more)"
            assert sf.result is not None  # narrowed by actionable_symbols filter above
            table.add_row(sf.symbol, sf.result.outcome.value, sf.result.detail, files)
        console.print(table)
    else:
        console.print(f"[green]No symbol issues[/green] ({len(symbol_findings)} distinct symbols checked)")

    if unresolved_symbols:
        console.print(
            f"[yellow]{len(unresolved_symbols)} symbol(s) skipped[/yellow]: pinned version couldn't be "
            "resolved from uv.lock or the running environment (not counted as OK — see "
            "docs/implementation-plan.md's Phase 4 entry)."
        )

    if actionable_deps or actionable_symbols:
        raise _typer.Exit(code=1)


def _run_semantic_sync(
    records: list[KnowledgeRecord],
    py_files: list[Path],
    repo_root: Path,
    config: ResyncConfig,
    apply: bool,
    model: Path | None,
    llama_server_binary: str,
    console: Console,
) -> None:
    """The `--tier semantic` implementation, factored out of `sync()` itself so that function's control
    flow reads linearly for the (much more common) mechanical case. Starts its own `llama-server` for the
    duration of the sweep and guarantees it's stopped afterward, success or failure — never leaves a model
    process (and the VRAM it holds) running past this command's own lifetime.
    """
    import typer as _typer
    from rich.table import Table

    from resync.cli.scan import extract_fully_qualified_symbols
    from resync.llm import llama_server
    from resync.llm.generator import GeneratorError, draft_patch
    from resync.patch.ast_grep_runner import _package_is_imported  # reused deliberately — see module note
    from resync.patch.taxonomy import PatchStrategy, classify
    from resync.verification.critic import LlamaServerCritic, VerificationContext

    if model is None:
        console.print(
            "[red]--tier semantic requires --model <path-to-gguf>.[/red] See docs/tech-stack.md for the "
            "recommended model (Qwen2.5-Coder-7B-Instruct, Q4_K_M) and docs/implementation-plan.md's Phase 6."
        )
        raise _typer.Exit(code=2)

    semantic_records = [r for r in records if classify(r, config.confidence.auto_apply_above) == PatchStrategy.SEMANTIC]
    console.print(f"{len(semantic_records)} of {len(records)} known changes classify as SEMANTIC.")
    if not semantic_records:
        return

    try:
        handle = llama_server.start(llama_server.LlamaServerConfig(model_path=model), binary=llama_server_binary)
    except llama_server.LlamaServerUnavailableError as exc:
        console.print(f"[red]Could not start the local model:[/red] {exc}")
        raise _typer.Exit(code=2) from None

    try:
        critic = LlamaServerCritic(handle.base_url)
        results_table = Table(title="Semantic sync" + (" (applied)" if apply else " (preview — pass --apply to write)"))
        results_table.add_column("File")
        results_table.add_column("Symbol")
        results_table.add_column("Critic verdict")

        for record in semantic_records:
            for py_file in py_files:
                if not _package_is_imported(py_file, record.package, "python"):
                    continue
                # A real gap, found in review: mechanical sync gates on the *specific symbol* actually
                # being called (ast_grep_runner's ast-grep patterns), but this loop used to gate only on
                # "the package is imported somewhere in the file" — far coarser. A large repo where many
                # files import `transformers` for unrelated reasons, but only a few call the one deprecated
                # symbol, would send every one of those unrelated files to the LLM: wasted calls, and a real
                # risk of a spurious "fix" where nothing in the file actually needed one. Gated more
                # precisely here using the same real, AST-based symbol resolution `resync check` already
                # uses (cli/scan.py's extract_fully_qualified_symbols) — it resolves imports properly rather
                # than a naive text search, so a same-named local variable or unrelated symbol doesn't
                # falsely pass this check either.
                if record.old_symbol not in extract_fully_qualified_symbols(py_file):
                    continue
                old_source = py_file.read_text()
                try:
                    draft = draft_patch(_describe_change(record), old_source, handle.base_url)
                except GeneratorError as exc:
                    results_table.add_row(
                        str(py_file.relative_to(repo_root)), record.old_symbol, f"[red]generator error: {exc}[/red]"
                    )
                    continue
                if draft.content == "UNABLE_TO_DRAFT":
                    results_table.add_row(
                        str(py_file.relative_to(repo_root)),
                        record.old_symbol,
                        "[yellow]model declined to draft[/yellow]",
                    )
                    continue

                verdict = critic.review(
                    draft,
                    VerificationContext(
                        old_source=old_source,
                        new_source=draft.content,
                        knowledge_record_summary=_describe_change(record),
                    ),
                )
                if verdict.approved:
                    results_table.add_row(
                        str(py_file.relative_to(repo_root)), record.old_symbol, "[green]approved[/green]"
                    )
                    if apply:
                        py_file.write_text(draft.content)
                else:
                    results_table.add_row(
                        str(py_file.relative_to(repo_root)),
                        record.old_symbol,
                        f"[red]rejected: {verdict.rejection_reason}[/red]",
                    )

        console.print(results_table)
    finally:
        llama_server.stop(handle)


def _describe_change(record: KnowledgeRecord) -> str:
    if record.parameter and record.new_parameter:
        return f"{record.old_symbol}: parameter `{record.parameter}` -> `{record.new_parameter}`"
    if record.new_symbol and record.new_symbol != record.old_symbol:
        return f"{record.old_symbol} renamed to {record.new_symbol}"
    return f"{record.old_symbol}: {record.rule_type.value}"


@app.command()
def sync(
    repo: Path = typer.Argument(Path("."), help="Repo to run the scheduled correction sweep against"),
    tier: str = typer.Option(
        "mechanical", help="mechanical | semantic | critical — see docs/architecture.md#two-speeds"
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write fixes to disk. Without this flag, only previews what would change."
    ),
    model: Path | None = typer.Option(
        None, "--model", help="Path to a local GGUF model file — required for --tier semantic."
    ),
    llama_server_binary: str = typer.Option(
        "llama-server", help="Name/path of the llama-server binary (Phase 6, --tier semantic only)."
    ),
) -> None:
    """Run one tier of the scheduled correction sweep.

    `--tier mechanical` finds every KnowledgeRecord classified MECHANICAL (patch/taxonomy.classify) and, for
    each repo file that imports the affected package, previews the ast-grep fix (or applies it, with
    `--apply`).

    `--tier semantic` (Phase 6): for every KnowledgeRecord classified SEMANTIC, drafts a rewrite via the
    local model (`llm/generator.py`) for each file that imports the affected package, then runs it through
    the adversarial critic pass (`verification/critic.LlamaServerCritic`) before ever considering `--apply`
    — a patch the critic doesn't approve is reported, never written, regardless of `--apply`. Requires
    `--model <path-to-gguf>`; starts and stops its own `llama-server` process for the duration of the sweep
    (`llm/llama_server.py`), never leaving one running afterward.

    `critical` needs a human reviewer in the loop by design and is not built — it raises rather than
    silently doing nothing.

    Does **not** open PRs, despite this command's docstring in earlier planning — PR creation needs a real
    git remote and an authenticated GitHub client (the GitHub App surface, docs/architecture.md#integration-
    surfaces), which is out of scope for this offline-first CLI command. This writes to the working tree (or
    previews doing so); committing and opening a PR is the caller's job, same as `git commit` after any other
    local tool run.
    """
    import typer as _typer
    from rich.console import Console
    from rich.table import Table

    from resync.config.loader import load as load_config
    from resync.knowledge import store
    from resync.patch import ast_grep_runner
    from resync.patch.taxonomy import PatchStrategy, classify

    if tier == "critical":
        console = Console()
        console.print(
            "[red]--tier critical is not implemented.[/red] Critical-tier changes need a human reviewer in "
            "the loop by design — this tier is intentionally never fully automated. See docs/architecture.md."
        )
        raise _typer.Exit(code=2)
    if tier not in ("mechanical", "semantic"):
        console = Console()
        console.print(f"[red]Unknown --tier {tier!r}.[/red] Expected mechanical, semantic, or critical.")
        raise _typer.Exit(code=2)

    repo_root = repo.resolve()
    console = Console()
    config = load_config(repo_root)

    db_path = store.default_db_path(repo_root)
    if not db_path.exists():
        console.print(
            f"[yellow]No knowledge store at {db_path}[/yellow] — nothing to check against. Run against a "
            "repo with a seeded/populated .resync/knowledge.lancedb first."
        )
        raise _typer.Exit(code=0)

    db = store.connect(db_path)
    table_handle = store.get_or_create_table(db)
    records = store.all_records(table_handle)
    py_files = [p for p in repo_root.rglob("*.py") if ".venv" not in p.parts and ".git" not in p.parts]

    if tier == "semantic":
        _run_semantic_sync(records, py_files, repo_root, config, apply, model, llama_server_binary, console)
        return

    mechanical_records = [
        r for r in records if classify(r, config.confidence.auto_apply_above) == PatchStrategy.MECHANICAL
    ]
    console.print(f"{len(mechanical_records)} of {len(records)} known changes classify as MECHANICAL.")

    results_table = Table(title="Mechanical sync" + (" (applied)" if apply else " (preview — pass --apply to write)"))
    results_table.add_column("File")
    results_table.add_column("Symbol")
    results_table.add_column("Matches")
    any_matches = False
    for record in mechanical_records:
        for py_file in py_files:
            if apply:
                matches = ast_grep_runner.apply(record, py_file, repo_root=repo_root)
            else:
                matches = ast_grep_runner.preview(record, py_file)
            if matches:
                any_matches = True
                results_table.add_row(str(py_file.relative_to(repo_root)), record.old_symbol, str(len(matches)))

    if any_matches:
        console.print(results_table)
    else:
        console.print("[green]No mechanical fixes needed.[/green]")


@app.command(name="mcp-config")
def mcp_config_command(
    client: str = typer.Argument(
        ...,
        help="A registered client id (run 'resync mcp-config-list' to see them and their verification "
        "dates), or 'custom' for any other MCP-compliant agent — see --root-key/--command-style/etc below.",
    ),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo to write a project-level config into"),
    name: str = typer.Option("resync", help="Server name/key to write the entry under"),
    print_only: bool = typer.Option(
        False, "--print", help="Print the config snippet instead of writing it to the client's real file"
    ),
    root_key: str = typer.Option(
        "mcpServers", help="[--client custom only] the top-level key holding the server map, e.g. 'mcpServers'"
    ),
    command_style: str = typer.Option(
        "separate",
        help="[--client custom only] separate | array | nested_object — see cli/mcp_config.py's module "
        "docstring for what each real client format actually looks like.",
    ),
    type_value: str | None = typer.Option(
        None, help="[--client custom only] value for a 'type' field, if that client's format uses one"
    ),
) -> None:
    """Add resync as an MCP server to a supported client, in that client's own real, verified config
    format — see `cli/mcp_config.py`'s module docstring for exactly what was verified about each one,
    including real, currently-documented client bugs this command deliberately avoids triggering (Claude
    Desktop deleting its own config on a `url` entry; a VS Code config silently failing without an explicit
    `"type"` field).

    Merges into the existing file rather than overwriting it — any other MCP servers or settings already in
    that file are left untouched. Antigravity is never auto-written (real, unresolved path uncertainty
    across its own product surfaces — see the module docstring); this prints the config snippet and where
    to paste it instead, the same as `--print` does for every other client.

    `--client custom` is the escape hatch for any MCP-compliant agent not yet in the registry: every
    compliant client accepts some command/args/env triple, so `--root-key`/`--command-style`/`--type-value`
    (read from that client's own docs) build the same shape a registered entry would, without waiting on a
    resync release first.
    """
    import typer as _typer
    from rich.console import Console

    from resync.cli.mcp_config import CLIENT_IDS, CommandStyle, format_custom, format_for_display, write_config

    console = Console()

    if client == "custom":
        if command_style not in ("separate", "array", "nested_object"):
            console.print(
                f"[red]Unknown --command-style {command_style!r}.[/red] Expected separate, array, or nested_object."
            )
            raise _typer.Exit(code=2)
        validated_style: CommandStyle = command_style  # type: ignore[assignment]  # membership just checked above
        console.print(format_custom(root_key=root_key, command_style=validated_style, type_value=type_value, name=name))
        console.print(
            "\n[yellow]Paste the snippet above into your agent's own MCP config file, under the key shown "
            "— this module doesn't know that file's location for an unregistered client.[/yellow]"
        )
        return

    if client not in CLIENT_IDS:
        console.print(
            f"[red]Unknown client {client!r}.[/red] Run 'resync mcp-config-list' to see registered clients, "
            "or pass 'custom' for any other MCP-compliant agent."
        )
        raise _typer.Exit(code=2)

    if client == "antigravity" or print_only:
        console.print(format_for_display(client, name=name))
        if client == "antigravity":
            console.print(
                "\n[yellow]Antigravity's config file location varies across its Desktop/IDE/CLI surfaces "
                "and has changed across recent versions — rather than guess, open Antigravity's own "
                "Settings → Customizations → Manage MCP Servers → View/Open raw config, and paste the "
                "snippet above into its mcpServers section.[/yellow]"
            )
        return

    try:
        path = write_config(client, repo.resolve(), name=name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise _typer.Exit(code=1) from None
    console.print(f"[green]Wrote {name} into {path}[/green]")
    if client == "claude-desktop":
        console.print("Restart Claude Desktop completely for the new server to be picked up.")


@app.command(name="mcp-config-list")
def mcp_config_list_command() -> None:
    """List every MCP client `resync mcp-config` has a registered, verified format for, with the date each
    format was last verified and any real, currently-known caveats — see `cli/mcp_config.py`'s module
    docstring for why this project tracks verification dates explicitly rather than implying a confidence
    in each format that isn't warranted for a space this many independently-versioned tools all move in.
    """
    from rich.console import Console
    from rich.table import Table

    from resync.cli.mcp_config import describe_registry

    console = Console()
    table = Table(title="Registered MCP client formats")
    table.add_column("Client")
    table.add_column("Last verified")
    table.add_column("Notes")
    for row in describe_registry():
        table.add_row(row["id"], row["last_verified"], row["notes"])
    console.print(table)
    console.print(
        "\nAny other MCP-compliant agent: [bold]resync mcp-config custom --root-key ... --command-style "
        "...[/bold] — see 'resync mcp-config --help'."
    )


if __name__ == "__main__":
    app()
