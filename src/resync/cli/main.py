"""Resync's CLI entry point.

See docs/architecture.md#integration-surfaces. This is the offline-first surface: a developer running
Resync locally against the 6-12GB VRAM local model, without the GitHub App or a remote MCP deployment.
"""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(help="An AI-native compatibility engine for dependencies, APIs, and the agents that write your code.")


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

    from resync.resolve.resolver import ResolverError, ResolverUnavailableError
    from resync.resolve.resolver import resolve as run_resolve
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


@app.command()
def sync(
    repo: Path = typer.Argument(Path("."), help="Repo to run the scheduled correction sweep against"),
    tier: str = typer.Option(
        "mechanical", help="mechanical | semantic | critical — see docs/architecture.md#two-speeds"
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write fixes to disk. Without this flag, only previews what would change."
    ),
) -> None:
    """Run one tier of the scheduled correction sweep.

    Only `--tier mechanical` is implemented: finds every KnowledgeRecord classified MECHANICAL
    (patch/taxonomy.classify) and, for each repo file that imports the affected package, previews the
    ast-grep fix (or applies it, with `--apply`). `semantic` needs Phase 6's local model (patch/critic.py is
    currently a Protocol seam only) and `critical` needs a human reviewer in the loop by design — neither is
    built yet, so both raise rather than silently doing nothing.

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

    if tier != "mechanical":
        console = Console()
        console.print(
            f"[red]--tier {tier} is not implemented yet.[/red] Only 'mechanical' is built — 'semantic' "
            "needs Phase 6's local model (patch/critic.py is a Protocol seam only), and 'critical' needs a "
            "human reviewer in the loop by design. See docs/implementation-plan.md."
        )
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

    mechanical_records = [
        r for r in records if classify(r, config.confidence.auto_apply_above) == PatchStrategy.MECHANICAL
    ]
    console.print(f"{len(mechanical_records)} of {len(records)} known changes classify as MECHANICAL.")

    py_files = [p for p in repo_root.rglob("*.py") if ".venv" not in p.parts and ".git" not in p.parts]

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


if __name__ == "__main__":
    app()
