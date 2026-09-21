"""Resync's CLI entry point.

See docs/architecture.md#integration-surfaces. This is the offline-first surface: a developer running
Resync locally against the 6-12GB VRAM local model, without the GitHub App or a remote MCP deployment.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    scaffold_mcp: bool | None = typer.Option(
        None,
        "--scaffold-mcp/--no-scaffold-mcp",
        help=(
            "Scaffold team MCP templates (.cursor, .vscode, .mcp.json, .agents, .zed) and update .gitignore. "
            "Omit to be asked interactively (defaults to no under --yes)."
        ),
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

    should_scaffold = scaffold_mcp if scaffold_mcp is not None else (False if yes else _confirm_scaffold(console))
    if should_scaffold:
        from resync.cli.mcp_config import scaffold_project_mcp_templates

        targets, unignores = scaffold_project_mcp_templates(repo_root)
        console.print(
            f"[green]Scaffolded {len(targets)} team MCP templates (.cursor, .vscode, .mcp.json, .agents, .zed).[/green]"
        )
        if unignores:
            console.print("\n[cyan]Updated .gitignore to unignore team MCP templates:[/cyan]")
            for rule in unignores:
                console.print(f"  [green]+[/green] {rule}")


def _confirm_seed(console: Console) -> bool:
    from rich.prompt import Confirm

    return Confirm.ask(
        "\nSeed the knowledge store with resync's built-in verified records now?", default=True, console=console
    )


def _confirm_scaffold(console: Console) -> bool:
    from rich.prompt import Confirm

    return Confirm.ask(
        "\nScaffold team MCP templates (.cursor, .vscode, .mcp.json, .agents, .zed) now?",
        default=False,
        console=console,
    )


@app.command()
def seed(
    repo: Path = typer.Argument(Path("."), help="Repo whose knowledge store should be seeded"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-seed even if the store already contains records"),
) -> None:
    """Seed the knowledge store (.resync/knowledge.lancedb) with built-in verified records."""
    from rich.console import Console

    from resync.cli.init_wizard import seed_knowledge_store
    from resync.knowledge import store

    console = Console()
    repo_root = repo.resolve()
    db_path = store.default_db_path(repo_root)

    if db_path.exists():
        try:
            db = store.connect(db_path)
            table = store.get_or_create_table(db)
            records = store.all_records(table)
            if records and not force:
                console.print(
                    f"[yellow]Knowledge store at {db_path} already contains {len(records)} record(s).[/yellow] "
                    "Use --force to re-seed."
                )
                return
        except Exception:
            pass

    seed_knowledge_store(repo_root, console)


@app.command()
def serve(
    transport: str = typer.Option("stdio", help="stdio | http — see docs/architecture.md#decision-1"),
    port: int = typer.Option(8787, help="Only used when --transport http"),
    repo: Path | None = typer.Option(
        None, help="Repo this server checks. Defaults to $RESYNC_REPO_ROOT, else the current directory."
    ),
) -> None:
    """Start the MCP server (local stdio process, or Streamable HTTP for team/remote use)."""
    from resync.server.app import run as run_server

    run_server(transport, repo_root=repo, port=port)


@app.command()
def dashboard(
    repo: Path = typer.Option(Path("."), "--repo", help="Repo to inspect and serve review dashboard for"),
    port: int = typer.Option(8787, "--port", "-p", help="Port to serve the dashboard on"),
    browser: bool = typer.Option(True, "--browser/--no-browser", help="Automatically open dashboard in web browser"),
) -> None:
    """Launch the interactive Resync Review & Explainability Dashboard in the browser."""
    import threading
    import time
    import webbrowser

    from rich.console import Console

    from resync.server.app import run as run_server

    console = Console()
    repo_root = repo.resolve()
    url = f"http://127.0.0.1:{port}/dashboard"

    console.print(
        f"\n[bold cyan]Starting Resync Review Dashboard on[/bold cyan] "
        f"[bold underline white]{url}[/bold underline white]\n"
    )

    if browser:

        def _open() -> None:
            time.sleep(1.0)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    run_server(transport="http", repo_root=repo_root, port=port)


@app.command()
def explain(
    target: str = typer.Argument(..., help="Symbol (e.g. transformers.pipeline) or package (e.g. requests) to explain"),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo whose knowledge store and config to consult"),
    version: str | None = typer.Option(None, "--version", "-v", help="Pinned version to check against"),
) -> None:
    """Explain root causes, migration paths, decomposed trust scores, and remediation options for an API change."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from resync.server.tools import explain_change

    console = Console()
    repo_root = repo.resolve()

    data = explain_change(target, repo_root, pinned_version=version)

    outcome = data["outcome"]
    kind = data["kind"]
    badge_style = (
        "green" if outcome == "ok" else ("yellow" if outcome in ("symbol_deprecated", "check_unavailable") else "red")
    )

    console.print(f"\n[bold]Explainability Report: [{badge_style}]{data['target']}[/{badge_style}][/bold] ({kind})\n")
    console.print(Panel(data["detail"], title=f"Verdict: {outcome.upper()}", border_style=badge_style))

    if data.get("explanation"):
        console.print(f"\n[bold cyan]Root Cause & Analysis:[/bold cyan]\n{data['explanation']}\n")

    tb = data.get("trust_breakdown")
    if tb:
        t_table = Table(
            title=f"Decomposed Trust Score: {tb.get('overall', 0.0):.2f} / 1.00 ({tb.get('verdict', 'N/A')})"
        )
        t_table.add_column("Rule Match", justify="center")
        t_table.add_column("Test Suite", justify="center")
        t_table.add_column("Differential Equivalence", justify="center")
        t_table.add_column("Source Citation", justify="center")
        t_table.add_row(
            f"{tb.get('rule_match', 0.0):.2f}",
            f"{tb.get('test_suite', 0.0):.2f}",
            f"{tb.get('differential_equivalence', 0.0):.2f}",
            f"{tb.get('source_citation', 0.0):.2f}",
        )
        console.print(t_table)

    options = data.get("options")
    if options:
        console.print("\n[bold]Actionable Remediation Options:[/bold]")
        for opt in options:
            action = opt["action"]
            color = (
                "green"
                if action == "Sync"
                else ("magenta" if action == "Shift" else ("yellow" if action == "Pin" else "red"))
            )
            cmd = f" ([dim]{opt['command']}[/dim])" if opt.get("command") else ""
            console.print(f"  [{color}][{action}][/{color}] [bold]{opt['title']}[/bold]: {opt['description']}{cmd}")
    console.print("")


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
    provenance: bool = typer.Option(
        True,
        "--provenance/--no-provenance",
        help="Run the Sigstore/SLSA provenance gate against resolved packages in uv.lock (requires network).",
    ),
    explain: bool = typer.Option(
        False,
        "--explain",
        help="Show decomposed trust scores, root cause explanations, and actionable remediation options.",
    ),
) -> None:
    """Run the fast verification checks (verify_package / check_symbol_exists) against an existing repo,
    without going through an agent's MCP call — useful as a pre-commit or CI step.

    Also runs the Sigstore/SLSA provenance gate against packages resolved in uv.lock (when present),
    surfacing attestation failures that `verify_package`'s OSV-only advisory check cannot catch.
    Use `--no-provenance` to skip the provenance gate (e.g. in offline or egress-restricted environments).
    """
    import typer as _typer
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from resync.cli.scan import (
        ProvenanceFinding,
        is_actionable,
        run_dependency_checks,
        run_provenance_checks,
        run_symbol_checks,
    )

    repo_root = repo.resolve()
    console = Console()

    console.print(f"[bold]Scanning {repo_root}[/bold]")

    from resync.knowledge import store

    db_path = store.default_db_path(repo_root)
    is_store_empty = True
    if db_path.exists():
        try:
            db = store.connect(db_path)
            table_handle = store.get_or_create_table(db)
            is_store_empty = len(store.all_records(table_handle)) == 0
        except Exception:
            is_store_empty = True

    if is_store_empty:
        console.print(
            f"[yellow]Warning: Knowledge store is unseeded or empty ({db_path}).[/yellow] "
            "Resync cannot detect known API breakages without records. Run 'resync seed' to populate built-in records."
        )

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

        if explain:
            console.print("\n[bold]Dependency Explainability & Remediation Options:[/bold]")
            for f in actionable_deps:
                opt_lines = []
                if f.result.options:
                    for opt in f.result.options:
                        cmd = f" (`{opt['command']}`)" if opt.get("command") else ""
                        opt_lines.append(f"  [{opt['action']}] {opt['title']}: {opt['description']}{cmd}")
                body = (f.result.explanation or f.result.detail) + ("\n\n" + "\n".join(opt_lines) if opt_lines else "")
                console.print(
                    Panel(
                        body,
                        title=f"{f.package} ({f.result.outcome.value})",
                        border_style="red"
                        if "not_found" in f.result.outcome.value or "advisory" in f.result.outcome.value
                        else "yellow",
                    )
                )
    else:
        console.print(f"[green]No dependency issues[/green] ({len(dep_findings)} checked)")

    if actionable_symbols:
        table = Table(title="Symbol issues")
        table.add_column("Symbol")
        table.add_column("Outcome")
        table.add_column("Tier")
        table.add_column("Detail")
        table.add_column("Files")
        for sf in actionable_symbols:
            files = ", ".join(str(p.relative_to(repo_root)) for p in sf.files[:3])
            if len(sf.files) > 3:
                files += f" (+{len(sf.files) - 3} more)"
            assert sf.result is not None  # narrowed by actionable_symbols filter above
            tier_label = sf.result.verification_tier or "—"
            table.add_row(sf.symbol, sf.result.outcome.value, tier_label, sf.result.detail, files)
        console.print(table)

        if explain:
            console.print("\n[bold]Symbol Explainability & Decomposed Trust:[/bold]")
            for sf in actionable_symbols:
                assert sf.result is not None
                tb = sf.result.trust_breakdown or {}
                tb_str = (
                    f"Trust: {tb.get('overall', 0.0):.2f} ("
                    f"Rule: {tb.get('rule_match', 0.0):.2f}, "
                    f"Tests: {tb.get('test_suite', 0.0):.2f}, "
                    f"Diff: {tb.get('differential_equivalence', 0.0):.2f}, "
                    f"Citation: {tb.get('source_citation', 0.0):.2f})"
                    if tb
                    else ""
                )
                opt_lines = []
                if sf.result.options:
                    for opt in sf.result.options:
                        cmd = f" (`{opt['command']}`)" if opt.get("command") else ""
                        opt_lines.append(f"  [{opt['action']}] {opt['title']}: {opt['description']}{cmd}")
                body = (
                    (sf.result.explanation or sf.result.detail)
                    + (f"\n\n{tb_str}" if tb_str else "")
                    + ("\n\n" + "\n".join(opt_lines) if opt_lines else "")
                )
                console.print(
                    Panel(
                        body,
                        title=f"{sf.symbol} ({sf.result.outcome.value})",
                        border_style="yellow" if sf.result.outcome.value == "symbol_deprecated" else "red",
                    )
                )
    else:
        console.print(f"[green]No symbol issues[/green] ({len(symbol_findings)} distinct symbols checked)")

    if unresolved_symbols:
        console.print(
            f"[yellow]{len(unresolved_symbols)} symbol(s) skipped[/yellow]: pinned version couldn't be "
            "resolved from uv.lock or the running environment (not counted as OK — see "
            "docs/implementation-plan.md's Phase 4 entry)."
        )

    # Provenance gate — only runs when uv.lock is present and --provenance is set (the default).
    prov_findings: list[ProvenanceFinding] = []
    any_prov_invalid = False
    if provenance:
        prov_findings = run_provenance_checks(repo_root)
        invalid_prov: list[ProvenanceFinding] = [f for f in prov_findings if f.outcome == "invalid"]
        unavailable_prov: list[ProvenanceFinding] = [f for f in prov_findings if f.outcome == "check_unavailable"]
        if prov_findings:
            if invalid_prov:
                any_prov_invalid = True
                prov_table = Table(title="Provenance failures (Sigstore/SLSA)")
                prov_table.add_column("Package")
                prov_table.add_column("Version")
                prov_table.add_column("Outcome")
                prov_table.add_column("Detail")
                for pf in invalid_prov:
                    prov_table.add_row(pf.package, pf.version, f"[bold red]{pf.outcome}[/bold red]", pf.detail)
                console.print(prov_table)
            elif unavailable_prov:
                console.print(
                    f"[yellow]Provenance gate: {len(unavailable_prov)} package(s) could not be checked "
                    "(network/TUF unavailable) — not a verdict.[/yellow]"
                )
            else:
                console.print(f"[green]Provenance gate: {len(prov_findings)} package(s) checked, no failures.[/green]")
        elif (repo_root / "uv.lock").exists():
            console.print("[dim]Provenance gate: uv.lock found but no packages to check.[/dim]")
        else:
            console.print("[dim]Provenance gate: no uv.lock found, skipped.[/dim]")

    if actionable_deps or actionable_symbols or any_prov_invalid:
        raise _typer.Exit(code=1)


def _run_semantic_sync(
    records: list[KnowledgeRecord],
    py_files: list[Path],
    repo_root: Path,
    config: ResyncConfig,
    apply: bool,
    force_wide: bool,
    model: Path | None,
    llama_server_binary: str,
    console: Console,
) -> None:
    """The `--tier semantic` implementation, factored out of `sync()` itself so that function's control
    flow reads linearly for the (much more common) mechanical case. Starts its own `llama-server` for the
    duration of the sweep and guarantees it's stopped afterward, success or failure — never leaves a model
    process (and the VRAM it holds) running past this command's own lifetime.
    """
    import difflib

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
        results_table = Table(title="Semantic sync" + (" (applied)" if apply else " (preview - pass --apply to write)"))
        results_table.add_column("File")
        results_table.add_column("Symbol")
        results_table.add_column("Critic verdict")
        results_table.add_column("Diff scope")

        for record in semantic_records:
            for py_file in py_files:
                if not _package_is_imported(py_file, record.package, "python"):
                    continue
                # Gate more precisely on the specific symbol actually being called, not just the package
                # being imported — avoids sending every file that imports `transformers` to the LLM when
                # only a few actually call the deprecated symbol. See audit finding in _run_semantic_sync.
                if record.old_symbol not in extract_fully_qualified_symbols(py_file):
                    continue
                old_source = py_file.read_text()
                try:
                    draft = draft_patch(_describe_change(record), old_source, handle.base_url)
                except GeneratorError as exc:
                    results_table.add_row(
                        str(py_file.relative_to(repo_root)), record.old_symbol, f"[red]generator error: {exc}[/red]", ""
                    )
                    continue
                if draft.content == "UNABLE_TO_DRAFT":
                    results_table.add_row(
                        str(py_file.relative_to(repo_root)),
                        record.old_symbol,
                        "[yellow]model declined to draft[/yellow]",
                        "",
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

                # Diff-scope guard: compute a unified diff between original and draft, count changed
                # lines, and flag diffs that touch far more than the vicinity of the known symbol.
                # A legitimate single-symbol rename should produce a small, surgical diff. A wide diff
                # means the LLM changed unrelated code — that's exactly the thing the critic prompt
                # asks it not to do, but a structural diff here is a deterministic backstop, not another
                # model call. `--force-wide` bypasses this guard for cases where a wide diff is expected
                # (e.g. a split that genuinely propagates across many sites in one file).
                diff_lines = list(
                    difflib.unified_diff(old_source.splitlines(), draft.content.splitlines(), lineterm="")
                )
                changed_count = sum(1 for ln in diff_lines if ln.startswith(("+ ", "- ")))
                # Heuristic: more than 20 changed lines for a single deprecated-symbol fix is suspicious.
                # Not a hard correctness rule — just a flag. The threshold is intentionally conservative
                # (better to flag a legitimate wide fix than silently land one that modifies unrelated code).
                _WIDE_DIFF_THRESHOLD = 20
                is_wide = changed_count > _WIDE_DIFF_THRESHOLD
                scope_label = (
                    f"[yellow]wide ({changed_count} lines)[/yellow]"
                    if is_wide
                    else f"[green]surgical ({changed_count} lines)[/green]"
                )

                if verdict.approved:
                    if is_wide and not force_wide:
                        results_table.add_row(
                            str(py_file.relative_to(repo_root)),
                            record.old_symbol,
                            "[yellow]approved but not applied (wide diff)[/yellow]",
                            scope_label,
                        )
                        console.print(
                            f"[yellow]  {py_file.name}: critic approved but diff touches {changed_count} lines — "
                            "pass --force-wide to apply wide diffs.[/yellow]"
                        )
                    else:
                        results_table.add_row(
                            str(py_file.relative_to(repo_root)),
                            record.old_symbol,
                            "[green]approved[/green]",
                            scope_label,
                        )
                        if apply:
                            temp_file = py_file.with_name(f".{py_file.name}.tmp")
                            temp_file.write_text(draft.content, encoding="utf-8")
                            temp_file.replace(py_file)
                else:
                    results_table.add_row(
                        str(py_file.relative_to(repo_root)),
                        record.old_symbol,
                        f"[red]rejected: {verdict.rejection_reason}[/red]",
                        scope_label,
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
    explain: bool = typer.Option(
        False, "--explain", help="Show decomposed trust scores and root cause explainability for changes."
    ),
    model: Path | None = typer.Option(
        None, "--model", help="Path to a local GGUF model file — required for --tier semantic."
    ),
    llama_server_binary: str = typer.Option(
        "llama-server", help="Name/path of the llama-server binary (Phase 6, --tier semantic only)."
    ),
    force_wide: bool = typer.Option(
        False,
        "--force-wide",
        help="Apply semantic fixes even when the diff scope is wider than the known symbol's vicinity. "
        "By default, wide diffs (>20 changed lines) are flagged but not applied — they may indicate the "
        "model touched unrelated code. Use this flag when a wide diff is expected (e.g. a split fix that "
        "genuinely propagates across many call sites in one file).",
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

    from resync.cli.scan import discover_python_files
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
    if not records:
        console.print(
            f"[yellow]Warning: Knowledge store is unseeded or empty ({db_path}).[/yellow] "
            "Resync cannot detect known API breakages without records. Run 'resync seed' to populate built-in records."
        )
        raise _typer.Exit(code=0)

    py_files = discover_python_files(repo_root)

    if tier == "semantic":
        _run_semantic_sync(records, py_files, repo_root, config, apply, force_wide, model, llama_server_binary, console)
        return

    mechanical_records = [
        r for r in records if classify(r, config.confidence.auto_apply_above) == PatchStrategy.MECHANICAL
    ]
    console.print(f"{len(mechanical_records)} of {len(records)} known changes classify as MECHANICAL.")

    from resync.verification.tier import evaluate_record_verification
    from resync.verification.trust_score import build_trust_score

    results_table = Table(title="Mechanical sync" + (" (applied)" if apply else " (preview - pass --apply to write)"))
    results_table.add_column("File")
    results_table.add_column("Symbol")
    results_table.add_column("Matches")
    results_table.add_column("Tier")
    results_table.add_column("Trust")
    any_matches = False
    matched_records: list[tuple[KnowledgeRecord, Any]] = []
    for record in mechanical_records:
        v_tier, diff_res = evaluate_record_verification(record, PatchStrategy.MECHANICAL)
        trust = build_trust_score(record, test_suite_passed=True, differential_result=diff_res)
        tier_label = v_tier.value
        trust_label = f"{trust.overall:.2f}"
        for py_file in py_files:
            if apply:
                matches = ast_grep_runner.apply(record, py_file, repo_root=repo_root)
            else:
                matches = ast_grep_runner.preview(record, py_file)
            if matches:
                any_matches = True
                matched_records.append((record, trust))
                results_table.add_row(
                    str(py_file.relative_to(repo_root)),
                    record.old_symbol,
                    str(len(matches)),
                    tier_label,
                    trust_label,
                )

    if any_matches:
        console.print(results_table)
        if explain:
            from rich.panel import Panel

            console.print("\n[bold]Decomposed Trust Breakdown & Root Causes:[/bold]")
            for rec, ts in matched_records:
                desc = _describe_change(rec)
                citation = getattr(rec, "source_url", None) or getattr(rec, "git_commit", None) or rec.source.value
                exp_text = (
                    f"Change: {desc}\n"
                    f"Trust Score: {ts.overall:.2f} / 1.00\n"
                    f"  - Rule Match: {ts.rule_match:.2f}\n"
                    f"  - Synthetic Test Suite: {ts.test_suite:.2f}\n"
                    f"  - Differential Equivalence: {ts.differential_equivalence:.2f}\n"
                    f"  - Source Citation: {ts.source_citation:.2f} ({citation})\n"
                    f"Remediation: Automated ast-grep AST rewrite ({rec.rule_type.value})"
                )
                console.print(Panel(exp_text, title=rec.old_symbol, border_style="cyan"))
    else:
        console.print("[green]No mechanical fixes needed.[/green]")


@app.command()
def run(
    repo: Path = typer.Argument(Path("."), help="Repo to run the complete compatibility workflow against"),
    apply: bool = typer.Option(
        False, "--apply", "-a", help="Write fixes to disk. Without this flag, only previews what would change."
    ),
    tier: str = typer.Option(
        "mechanical", help="mechanical | semantic | critical — see docs/architecture.md#two-speeds"
    ),
    explain: bool = typer.Option(
        False,
        "--explain",
        help="Show decomposed trust scores and root cause explainability across both scan and sync.",
    ),
    provenance: bool = typer.Option(
        True,
        "--provenance/--no-provenance",
        help="Run the Sigstore/SLSA provenance gate against resolved packages in uv.lock.",
    ),
    model: Path | None = typer.Option(
        None, "--model", help="Path to a local GGUF model file — required for --tier semantic."
    ),
    llama_server_binary: str = typer.Option(
        "llama-server", help="Name/path of the llama-server binary (Phase 6, --tier semantic only)."
    ),
    force_wide: bool = typer.Option(
        False,
        "--force-wide",
        help="Apply semantic fixes even when the diff scope is wider than the known symbol's vicinity.",
    ),
) -> None:
    """Run the complete Resync compatibility workflow: scan, verify, and correct.

    Executes both the real-time verification sweep (check) and the scheduled
    correction sweep (sync). Pass `--apply` to automatically write fixes to disk.
    """
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from resync.cli.scan import (
        discover_python_files,
        is_actionable,
        run_dependency_checks,
        run_provenance_checks,
        run_symbol_checks,
    )
    from resync.config.loader import load as load_config
    from resync.knowledge import store
    from resync.patch import ast_grep_runner
    from resync.patch.taxonomy import PatchStrategy, classify
    from resync.verification.tier import evaluate_record_verification
    from resync.verification.trust_score import build_trust_score

    repo_root = repo.resolve()
    console = Console()

    console.print(f"\n[bold cyan]== Resync Compatibility Engine: Full Sweep ==[/bold cyan] [dim]({repo_root})[/dim]\n")

    # 1. Check phase: dependencies and symbols
    dep_findings = run_dependency_checks(repo_root)
    symbol_findings = run_symbol_checks(repo_root)

    actionable_deps = [f for f in dep_findings if is_actionable(f.result.outcome)]
    actionable_symbols = [f for f in symbol_findings if f.result is not None and is_actionable(f.result.outcome)]

    if actionable_deps:
        table = Table(title="Dependency issues")
        table.add_column("Package")
        table.add_column("Outcome")
        table.add_column("Detail")
        for f in actionable_deps:
            table.add_row(f.package, f.result.outcome.value, f.result.detail)
        console.print(table)
        if explain:
            console.print("\n[bold]Dependency Explainability & Options:[/bold]")
            for f in actionable_deps:
                body = f.result.explanation or f.result.detail
                console.print(Panel(body, title=f.package, border_style="yellow"))
    else:
        console.print(f"[green]Dependencies:[/green] No dependency issues ({len(dep_findings)} checked)")

    if actionable_symbols:
        table = Table(title="Symbol issues")
        table.add_column("Symbol")
        table.add_column("Outcome")
        table.add_column("Tier")
        table.add_column("Detail")
        table.add_column("Files")
        for sf in actionable_symbols:
            files = ", ".join(str(p.relative_to(repo_root)) for p in sf.files[:3])
            if len(sf.files) > 3:
                files += f" (+{len(sf.files) - 3} more)"
            assert sf.result is not None
            tier_label = sf.result.verification_tier or "-"
            table.add_row(sf.symbol, sf.result.outcome.value, tier_label, sf.result.detail, files)
        console.print(table)
        if explain:
            console.print("\n[bold]Symbol Explainability & Decomposed Trust:[/bold]")
            for sf in actionable_symbols:
                assert sf.result is not None
                tb = sf.result.trust_breakdown or {}
                tb_str = (
                    f"Trust: {tb.get('overall', 0.0):.2f} ("
                    f"Rule: {tb.get('rule_match', 0.0):.2f}, "
                    f"Tests: {tb.get('test_suite', 0.0):.2f}, "
                    f"Diff: {tb.get('differential_equivalence', 0.0):.2f}, "
                    f"Citation: {tb.get('source_citation', 0.0):.2f})"
                    if tb
                    else ""
                )
                body = (sf.result.explanation or sf.result.detail) + (f"\n\n{tb_str}" if tb_str else "")
                console.print(Panel(body, title=sf.symbol, border_style="yellow"))
    else:
        console.print(f"[green]Symbols:[/green] No broken symbol issues ({len(symbol_findings)} checked)")

    # Provenance gate
    if provenance:
        prov_findings = run_provenance_checks(repo_root)
        invalid_prov = [f for f in prov_findings if f.outcome == "invalid"]
        if invalid_prov:
            prov_table = Table(title="Provenance failures (Sigstore/SLSA)")
            prov_table.add_column("Package")
            prov_table.add_column("Version")
            prov_table.add_column("Outcome")
            prov_table.add_column("Detail")
            for pf in invalid_prov:
                prov_table.add_row(pf.package, pf.version, f"[bold red]{pf.outcome}[/bold red]", pf.detail)
            console.print(prov_table)
        elif prov_findings:
            console.print(f"[green]Provenance:[/green] {len(prov_findings)} package(s) verified.")

    console.print("")

    # 2. Correction phase (sync)
    config = load_config(repo_root)
    db_path = store.default_db_path(repo_root)
    if not db_path.exists():
        console.print(f"[yellow]Notice:[/yellow] Knowledge store at {db_path} is unseeded. Run 'resync seed'.")
        return

    db = store.connect(db_path)
    table_handle = store.get_or_create_table(db)
    records = store.all_records(table_handle)
    if not records:
        console.print("[yellow]Notice:[/yellow] Knowledge store has no records. Run 'resync seed'.")
        return

    py_files = discover_python_files(repo_root)

    if tier == "semantic":
        _run_semantic_sync(records, py_files, repo_root, config, apply, force_wide, model, llama_server_binary, console)
        return

    mechanical_records = [
        r for r in records if classify(r, config.confidence.auto_apply_above) == PatchStrategy.MECHANICAL
    ]

    results_table = Table(title="Correction Engine" + (" (applied)" if apply else " (preview - pass --apply to write)"))
    results_table.add_column("File")
    results_table.add_column("Symbol")
    results_table.add_column("Matches")
    results_table.add_column("Tier")
    results_table.add_column("Trust")
    any_matches = False
    matched_recs: list[tuple[KnowledgeRecord, Any]] = []

    for record in mechanical_records:
        v_tier, diff_res = evaluate_record_verification(record, PatchStrategy.MECHANICAL)
        trust = build_trust_score(record, test_suite_passed=True, differential_result=diff_res)
        tier_label = v_tier.value
        trust_label = f"{trust.overall:.2f}"
        for py_file in py_files:
            if apply:
                matches = ast_grep_runner.apply(record, py_file, repo_root=repo_root)
            else:
                matches = ast_grep_runner.preview(record, py_file)
            if matches:
                any_matches = True
                matched_recs.append((record, trust))
                results_table.add_row(
                    str(py_file.relative_to(repo_root)),
                    record.old_symbol,
                    str(len(matches)),
                    tier_label,
                    trust_label,
                )

    if any_matches:
        console.print(results_table)
        if explain:
            console.print("\n[bold]Decomposed Trust Breakdown & Fix Details:[/bold]")
            for rec, ts in matched_recs:
                desc = _describe_change(rec)
                citation = getattr(rec, "source_url", None) or getattr(rec, "git_commit", None) or rec.source.value
                exp_text = (
                    f"Change: {desc}\n"
                    f"Trust Score: {ts.overall:.2f} / 1.00\n"
                    f"  - Rule Match: {ts.rule_match:.2f}\n"
                    f"  - Synthetic Test Suite: {ts.test_suite:.2f}\n"
                    f"  - Differential Equivalence: {ts.differential_equivalence:.2f}\n"
                    f"  - Source Citation: {ts.source_citation:.2f} ({citation})"
                )
                console.print(Panel(exp_text, title=rec.old_symbol, border_style="cyan"))
        if apply:
            console.print("\n[bold green]Resync run complete: fixes applied successfully to disk.[/bold green]\n")
        else:
            console.print("\n[bold cyan]Preview complete. To apply these fixes to disk, run:[/bold cyan]")
            console.print("    [bold white]resync run --apply[/bold white]\n")
    else:
        console.print("[green]Correction Engine:[/green] Codebase matches all verified compatibility rules.\n")
        console.print("[bold green]Resync run complete: codebase is clean and compatible.[/bold green]\n")


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
    verify: bool = typer.Option(
        False,
        "--verify",
        help="After writing, verify the config actually works: for Claude Code/Cursor, ask that client's "
        "own headless CLI whether it sees resync (Tier A); otherwise (or if that CLI is unavailable), "
        "spawn `resync serve` directly and run a real MCP handshake against it (Tier B) — see "
        "cli/mcp_verify.py. Opt-in: it spawns a real process and takes a few seconds. Reports "
        "'unavailable' rather than a false pass when no check can actually run.",
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

    if client == "auto":
        console.print("[dim]Note: 'resync mcp-config auto' is an alias for 'resync mcp-config-auto'.[/dim]")
        mcp_config_auto_command(repo=repo, name=name)
        return
    if client == "list":
        console.print("[dim]Note: 'resync mcp-config list' is an alias for 'resync mcp-config-list'.[/dim]")
        mcp_config_list_command()
        return

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
            "-- this module doesn't know that file's location for an unregistered client.[/yellow]"
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
                "and has changed across recent versions -- rather than guess, open Antigravity's own "
                "Settings -> Customizations -> Manage MCP Servers -> View/Open raw config, and paste the "
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

    if verify:
        from resync.cli.mcp_verify import verify_client_config

        console.print(f"Verifying the {client} config ({name})...")
        result = verify_client_config(client, repo.resolve(), name=name)
        tier_label = "asked the real client" if result.tier == "A" else "direct spawn-and-handshake"
        if result.status == "verified":
            console.print(f"[green]Verified[/green] ({tier_label}): {result.detail}")
        elif result.status == "unavailable":
            console.print(f"[yellow]Unavailable[/yellow] ({tier_label}): {result.detail}")
        else:
            console.print(f"[red]Failed[/red] ({tier_label}): {result.detail}")
            raise _typer.Exit(code=1)


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


@app.command(name="mcp-config-auto")
def mcp_config_auto_command(
    repo: Path = typer.Option(Path("."), "--repo", help="Repo to inspect and configure"),
    name: str = typer.Option("resync", help="Server name/key to write the entry under"),
    all_targets: bool = typer.Option(
        False,
        "--all",
        "-a",
        help=(
            "Configure all repository-level agent templates (.cursor, .vscode, .zed, etc.) "
            "even if not currently present on disk"
        ),
    ),
) -> None:
    """Automatically detect all present AI coding agents (Antigravity, Claude Code, Cursor, VS Code,
    Claude Desktop, Windsurf, Zed), adapt to their existing configuration schemas, and non-destructively
    register the Resync MCP server across all of them."""
    from rich.console import Console
    from rich.table import Table

    from resync.cli.mcp_config import detect_agent_config_targets, ensure_gitignore_unignores, write_target_config

    console = Console()
    repo_root = repo.resolve()
    targets = detect_agent_config_targets(repo_root, all_project_targets=all_targets)

    if not targets:
        console.print("[yellow]No AI coding agent environments were detected.[/yellow]")
        return

    table = Table(title="Configured AI Coding Agents (MCP Server)")
    table.add_column("Agent")
    table.add_column("Scope")
    table.add_column("Target Config File")
    table.add_column("Status")

    success_count = 0
    configured_targets = []
    for target in targets:
        try:
            path = write_target_config(target, name=name)
            scope = "Global" if target.is_global else "Workspace"
            status_text = (
                "[green]Configured (Project Template)[/green]"
                if all_targets
                else "[green]Configured (Adaptive)[/green]"
            )
            table.add_row(target.display_name, scope, str(path), status_text)
            success_count += 1
            configured_targets.append(target)
        except Exception as exc:
            scope = "Global" if target.is_global else "Workspace"
            table.add_row(target.display_name, scope, str(target.path), f"[red]Error: {exc}[/red]")

    console.print(table)
    console.print(f"\n[green]Successfully configured Resync MCP server across {success_count} agent targets.[/green]")

    if all_targets:
        unignores = ensure_gitignore_unignores(repo_root, configured_targets)
        if unignores:
            console.print("\n[cyan]Updated .gitignore to ensure team MCP templates are tracked by git:[/cyan]")
            for rule in unignores:
                console.print(f"  [green]+[/green] {rule}")


@app.command(name="mcp-config-scaffold", hidden=True)
def mcp_config_scaffold_command(
    repo: Path = typer.Option(Path("."), "--repo", help="Repo to scaffold team MCP templates in"),
    name: str = typer.Option("resync", help="Server name/key to write the entry under"),
) -> None:
    """Pre-populate team-shareable MCP configuration templates across all supported AI coding agents
    (.cursor/mcp.json, .vscode/mcp.json, .mcp.json, .agents/mcp_config.json, .zed/settings.json),
    ensuring that .gitignore tracks the templates for team distribution."""
    from rich.console import Console
    from rich.table import Table

    from resync.cli.mcp_config import scaffold_project_mcp_templates

    console = Console()
    repo_root = repo.resolve()
    targets, unignores = scaffold_project_mcp_templates(repo_root, name=name)

    table = Table(title="Team MCP Configuration Templates Scaffolded")
    table.add_column("Agent")
    table.add_column("Configuration Template Path")
    table.add_column("Status")

    for target in targets:
        table.add_row(target.display_name, str(target.path), "[green]Ready for Team Distribution[/green]")

    console.print(table)
    console.print(f"\n[green]Scaffolded {len(targets)} team MCP templates ready to be committed to git.[/green]")

    if unignores:
        console.print("\n[cyan]Updated .gitignore to unignore team MCP templates:[/cyan]")
        for rule in unignores:
            console.print(f"  [green]+[/green] {rule}")


@app.command()
def ingest(
    package: str = typer.Argument(..., help="Package name on PyPI, e.g. 'transformers' or 'peft'"),
    old_version: str = typer.Argument(..., help="Baseline package version to diff from, e.g. '4.31.0'"),
    new_version: str = typer.Argument(..., help="Target package version to diff to, e.g. '4.32.0'"),
    apply: bool = typer.Option(
        False, "--apply", help="Upsert discovered breaking changes into .resync/knowledge.lancedb (preview by default)"
    ),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo whose knowledge store to update"),
    ecosystem: str = typer.Option("pypi", "--ecosystem", help="Target package ecosystem (currently pypi)"),
) -> None:
    """Ingest API breaking changes between two versions of a package via static AST diffing.

    By default, runs in preview mode: discovers breakages, correlates renames, detects reorders,
    and displays a formatted table with rule classifications and confidence scores.
    Pass --apply to write the discovered records directly into the repository's knowledge store.
    """
    import typer as _typer
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from resync.adapters.python.extract_api_diff import extract
    from resync.knowledge import store

    console = Console()
    repo_root = repo.resolve()

    console.print(f"[bold]Diffing {package} {old_version} -> {new_version} via static AST inspection...[/bold]")

    try:
        records = extract(
            package=package,
            old_ref=old_version,
            new_ref=new_version,
            from_version=old_version,
            to_version=new_version,
            ecosystem=ecosystem,
        )
    except Exception as exc:
        console.print(f"[red]Failed to extract API diff for {package}:[/red] {exc}")
        raise _typer.Exit(code=1) from exc

    if not records:
        console.print(f"[green]No breaking changes found between {package} {old_version} and {new_version}.[/green]")
        return

    table = Table(title=f"Discovered {len(records)} breaking change(s) in {package}")
    table.add_column("Rule Type", style="bold cyan")
    table.add_column("Old Symbol / Parameter")
    table.add_column("New Symbol / Parameter")
    table.add_column("Confidence", justify="right")

    for rec in records:
        old_desc = f"{rec.old_symbol}" + (f" ({rec.parameter})" if rec.parameter else "")
        new_desc = (f"{rec.new_symbol}" if rec.new_symbol else "-") + (
            f" ({rec.new_parameter})" if rec.new_parameter else ""
        )
        table.add_row(rec.rule_type.value, old_desc, new_desc, f"{rec.confidence:.2f}")

    console.print(table)
    console.print(
        Panel.fit(
            "[dim]Note: Records derived via static AST diffing carry confidence scores. "
            "Those below the project's auto-apply threshold will require review.[/dim]",
            border_style="dim",
        )
    )

    if apply:
        db_path = store.default_db_path(repo_root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = store.connect(db_path)
        table_handle = store.get_or_create_table(db)
        store.upsert(table_handle, records)
        console.print(f"[green]Successfully upserted {len(records)} record(s) into {db_path}[/green]")
    else:
        console.print(
            "\n[yellow]Preview mode only.[/yellow] Pass [bold cyan]--apply[/bold cyan] "
            "to persist these records to the knowledge store."
        )


@app.command()
def doctor(
    repo: Path = typer.Argument(Path("."), help="Repo root to run diagnostics against"),
    fix: bool = typer.Option(False, "--fix", help="Interactively remediate repairable issues"),
) -> None:
    """Diagnose environment health, binary dependencies, configuration, knowledge store, and agent integrations."""
    import json
    import shutil
    import subprocess
    import sys

    import httpx
    from rich.console import Console
    from rich.prompt import Confirm
    from rich.table import Table

    from resync.cli.init_wizard import seed_knowledge_store
    from resync.cli.mcp_config import (
        REGISTRY,
        detect_agent_config_targets,
        scaffold_project_mcp_templates,
    )
    from resync.config.loader import load as load_config
    from resync.knowledge import store
    from resync.server.tools import get_package_cache_stats

    console = Console()
    repo_root = repo.resolve()

    console.print(f"\n[bold cyan]Running Resync System Doctor for {repo_root}...[/bold cyan]\n")

    table = Table(title="System & Environment Diagnostics")
    table.add_column("Subsystem", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    needs_seed = False
    needs_mcp_scaffold = False

    # 1. Python runtime
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):  # noqa: UP036
        table.add_row("Python Runtime", "[green]PASS[/green]", f"Python {py_ver} (supported)")
    else:
        table.add_row("Python Runtime", "[red]FAIL[/red]", f"Python {py_ver} (requires Python >= 3.11)")

    # 2. uv binary
    uv_bin = shutil.which("uv")
    if uv_bin:
        try:
            res = subprocess.run([uv_bin, "--version"], capture_output=True, text=True, timeout=5)
            ver_str = res.stdout.strip() if res.returncode == 0 else "found"
            table.add_row("uv Resolver", "[green]PASS[/green]", f"{ver_str} ({uv_bin})")
        except Exception as exc:
            table.add_row("uv Resolver", "[yellow]WARN[/yellow]", f"uv present but failed: {exc}")
    else:
        table.add_row("uv Resolver", "[red]FAIL[/red]", "uv not found on PATH (required for dependency resolution)")

    # 3. ast-grep binary
    ag_bin = shutil.which("ast-grep")
    if ag_bin:
        try:
            res = subprocess.run([ag_bin, "--version"], capture_output=True, text=True, timeout=5)
            ver_str = res.stdout.strip() if res.returncode == 0 else "found"
            table.add_row("ast-grep Binary", "[green]PASS[/green]", f"{ver_str} ({ag_bin})")
        except Exception as exc:
            table.add_row("ast-grep Binary", "[yellow]WARN[/yellow]", f"ast-grep present but failed: {exc}")
    else:
        table.add_row(
            "ast-grep Binary",
            "[red]FAIL[/red]",
            "ast-grep not found on PATH (required for mechanical patching)",
        )

    # 4. resync.toml configuration
    config_file = repo_root / "resync.toml"
    if config_file.exists():
        try:
            cfg = load_config(repo_root)
            table.add_row(
                "resync.toml",
                "[green]PASS[/green]",
                f"Valid (mode: {cfg.project.mode}, {len(cfg.pin)} pins)",
            )
        except Exception as exc:
            table.add_row("resync.toml", "[red]FAIL[/red]", f"Configuration error: {exc}")
    else:
        table.add_row("resync.toml", "[yellow]WARN[/yellow]", "Not found. Run 'resync init' to initialize.")

    # 5. Knowledge Store
    db_path = store.default_db_path(repo_root)
    if db_path.exists():
        try:
            db = store.connect(db_path)
            tbl = store.get_or_create_table(db)
            records = store.all_records(tbl)
            if records:
                table.add_row("Knowledge Store", "[green]PASS[/green]", f"{len(records)} record(s) in {db_path.name}")
            else:
                needs_seed = True
                table.add_row(
                    "Knowledge Store",
                    "[yellow]WARN[/yellow]",
                    "Database exists but has 0 records. Run 'resync seed'.",
                )
        except Exception as exc:
            needs_seed = True
            table.add_row("Knowledge Store", "[yellow]WARN[/yellow]", f"Failed opening {db_path.name}: {exc}")
    else:
        needs_seed = True
        table.add_row("Knowledge Store", "[yellow]WARN[/yellow]", f"Uninitialized at {db_path}. Run 'resync seed'.")

    # 6. Manifest & Lockfile
    all_manifests: list[str] = []
    for f in [
        repo_root / "pyproject.toml",
        repo_root / "requirements.txt",
        repo_root / "package.json",
        repo_root / "Cargo.toml",
        repo_root / "go.mod",
        repo_root / "build.gradle.kts",
        repo_root / "build.gradle",
        repo_root / "pom.xml",
    ]:
        if f.exists():
            all_manifests.append(f.name)

    _ignored = (".venv", "venv", ".git", "node_modules", "dist", "build", "__pycache__", ".gradle", ".idea")
    try:
        for sub in repo_root.iterdir():
            if sub.is_dir() and sub.name not in _ignored:
                for sub_f in [
                    sub / "package.json",
                    sub / "requirements.txt",
                    sub / "pyproject.toml",
                    sub / "build.gradle.kts",
                    sub / "build.gradle",
                    sub / "pom.xml",
                    sub / "go.mod",
                    sub / "gradle" / "libs.versions.toml",
                ]:
                    if sub_f.exists():
                        rel = sub_f.relative_to(repo_root).as_posix()
                        all_manifests.append(rel)
    except Exception:
        pass

    if all_manifests:
        uv_lock = repo_root / "uv.lock"
        extra = " (with uv.lock)" if uv_lock.exists() else ""
        manifest_summary = ", ".join(all_manifests[:4])
        if len(all_manifests) > 4:
            manifest_summary += f" (+{len(all_manifests) - 4} more)"
        table.add_row("Project Manifest", "[green]PASS[/green]", f"{manifest_summary}{extra}")
    else:
        table.add_row("Project Manifest", "[yellow]WARN[/yellow]", "No project manifests found")

    # 7. AI Agent Integrations
    targets = detect_agent_config_targets(repo_root, all_project_targets=True)
    active_agents: list[str] = []
    for target in targets:
        if target.path.exists():
            try:
                data = json.loads(target.path.read_text(encoding="utf-8"))
                spec = REGISTRY.get(target.client_key)
                root_key = spec.root_key if spec else "mcpServers"
                servers = data.get(root_key, {})
                if "resync" in servers:
                    active_agents.append(target.display_name)
            except Exception:
                pass

    if active_agents:
        table.add_row("Agent Configs", "[green]PASS[/green]", f"Configured for: {', '.join(active_agents)}")
    else:
        needs_mcp_scaffold = True
        table.add_row(
            "Agent Configs",
            "[yellow]WARN[/yellow]",
            "No project MCP configs found. Run 'resync mcp-config-auto'.",
        )

    # 8. Network Egress Reachability
    endpoints = [
        ("PyPI Registry", "https://pypi.org"),
        ("OSV Advisory API", "https://api.osv.dev/v1/query"),
        ("Sigstore TUF", "https://tuf-repo-cdn.sigstore.dev"),
    ]
    try:
        with httpx.Client(timeout=3.0) as client:
            for name, url in endpoints:
                try:
                    resp = client.get(url)
                    if resp.status_code in (200, 301, 302, 400, 404, 405):
                        table.add_row(name, "[green]PASS[/green]", f"Reachable (HTTP {resp.status_code})")
                    else:
                        table.add_row(name, "[yellow]WARN[/yellow]", f"Unexpected HTTP status {resp.status_code}")
                except Exception as exc:
                    table.add_row(name, "[yellow]WARN[/yellow]", f"Egress unavailable: {exc}")
    except Exception as exc:
        table.add_row("Network Egress", "[yellow]WARN[/yellow]", f"Network client error: {exc}")

    # 9. In-Memory Cache Stats
    cache_stats = get_package_cache_stats()
    table.add_row(
        "Package Cache",
        "[green]PASS[/green]",
        f"Hits: {cache_stats['hits']}, Misses: {cache_stats['misses']}",
    )

    # 10. Language Adapter Discovery
    try:
        from resync.adapters.registry import list_supported_languages

        all_langs = list_supported_languages()
        lang_table = Table(title="Language Adapter Support (auto-discovered)")
        lang_table.add_column("Language", style="bold")
        lang_table.add_column("Ecosystem", style="cyan")
        lang_table.add_column("Required Tools", justify="center")
        lang_table.add_column("Optional Tools")
        lang_table.add_column("Status", justify="center")

        for meta in sorted(all_langs, key=lambda m: -m.priority):
            if meta.required_tools:
                missing_req = [t for t in meta.required_tools if not shutil.which(t)]
                req_status = (
                    "[green]" + ", ".join(meta.required_tools) + "[/green]"
                    if not missing_req
                    else "[red]" + ", ".join(missing_req) + " missing[/red]"
                )
                status = "[green]ACTIVE[/green]" if not missing_req else "[red]SKIP[/red]"
            else:
                req_status = "[dim]none[/dim]"
                status = "[green]ACTIVE[/green]"

            opt_parts: list[str] = []
            for opt_tool in meta.optional_tools:
                if shutil.which(opt_tool):
                    opt_parts.append(f"[green]{opt_tool}[/green]")
                else:
                    opt_parts.append(f"[dim]{opt_tool}[/dim]")
            opt_str = "  ".join(opt_parts) if opt_parts else "[dim]none[/dim]"

            lang_table.add_row(meta.display_name, meta.ecosystem, req_status, opt_str, status)

        console.print(lang_table)
        console.print("[dim]Install third-party language adapters with: pip install resync-adapter-<lang>[/dim]\n")
    except Exception as exc:
        console.print(f"[yellow]Language adapter discovery failed: {exc}[/yellow]\n")

    console.print(table)

    if fix:
        seed_prompt = "\nKnowledge store is missing or empty. Seed it now?"
        if needs_seed and Confirm.ask(seed_prompt, default=True, console=console):
            seed_knowledge_store(repo_root, console)
        mcp_prompt = "\nConfigure project MCP templates for Cursor, VS Code, Zed, etc. now?"
        if needs_mcp_scaffold and Confirm.ask(mcp_prompt, default=True, console=console):
            targets_scaffolded, _ = scaffold_project_mcp_templates(repo_root)
            console.print(f"[green]Configured {len(targets_scaffolded)} templates.[/green]")


if __name__ == "__main__":
    app()
