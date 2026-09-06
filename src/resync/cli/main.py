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
) -> None:
    """Start the MCP server (local stdio process, or Streamable HTTP for team/remote use)."""
    raise NotImplementedError


@app.command()
def check(
    repo: Path = typer.Argument(Path("."), help="Repo to run the real-time verification sweep against"),
) -> None:
    """Run the fast verification checks (verify_package / check_symbol_exists) against an existing repo,
    without going through an agent's MCP call — useful as a pre-commit or CI step."""
    raise NotImplementedError


@app.command()
def sync(
    repo: Path = typer.Argument(Path("."), help="Repo to run the scheduled correction sweep against"),
    tier: str = typer.Option("mechanical", help="mechanical | semantic | critical — see docs/architecture.md#two-speeds"),
) -> None:
    """Run one tier of the scheduled correction sweep and open PR(s) for what it finds."""
    raise NotImplementedError


if __name__ == "__main__":
    app()
