"""Integration coverage for `resync sync --tier mechanical` (cli/main.py) end-to-end: a real seeded LanceDB
knowledge store, a real repo directory containing the same fixture file used by
tests/integration/test_ast_grep_runner.py, and the real ast-grep binary doing the rewrite — driven through
Typer's CliRunner, the same entry point a real terminal invocation goes through, not by calling internal
functions directly.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resync.cli.main import app
from resync.knowledge import store
from resync.knowledge.seed_data import SEED_RECORDS

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fake_embed(text: str) -> list[float]:
    return [0.0] * store.EMBEDDING_DIM


@pytest.fixture
def seeded_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(store, "embed_document", _fake_embed)
    db_path = store.default_db_path(tmp_path)
    db_path.parent.mkdir(parents=True)
    table = store.get_or_create_table(store.connect(db_path))
    store.upsert(table, SEED_RECORDS)
    shutil.copy(FIXTURES / "transformers-param-rename" / "sample.py", tmp_path / "sample.py")
    return tmp_path


def test_sync_preview_reports_matches_without_writing(seeded_repo: Path) -> None:
    runner = CliRunner()
    original = (seeded_repo / "sample.py").read_text()

    result = runner.invoke(app, ["sync", str(seeded_repo), "--tier", "mechanical"])

    assert result.exit_code == 0, result.output
    assert "sample.py" in result.output
    assert (seeded_repo / "sample.py").read_text() == original  # preview must not touch the file


def test_sync_apply_actually_rewrites_the_file(seeded_repo: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["sync", str(seeded_repo), "--tier", "mechanical", "--apply"])

    assert result.exit_code == 0, result.output
    rewritten = (seeded_repo / "sample.py").read_text()
    assert "use_auth_token" not in rewritten
    assert "token=" in rewritten


def test_sync_unimplemented_tier_exits_nonzero_without_pretending_to_do_nothing_silently(tmp_path: Path) -> None:
    """`semantic` is now real (Phase 6) — this test now targets `critical`, the one tier still genuinely
    unimplemented by design (needs a human reviewer in the loop, never fully automated; see cli/main.py's
    `sync` docstring). Updated rather than deleted when semantic landed, per this project's own convention
    of correcting a stale test to match reality instead of leaving it asserting outdated behavior."""
    runner = CliRunner()
    result = runner.invoke(app, ["sync", str(tmp_path), "--tier", "critical"])
    assert result.exit_code == 2
    assert "not implemented" in result.output.lower()


def test_sync_unknown_tier_exits_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["sync", str(tmp_path), "--tier", "nonsense"])
    assert result.exit_code == 2


def test_sync_with_no_knowledge_store_exits_cleanly(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["sync", str(tmp_path), "--tier", "mechanical"])
    assert result.exit_code == 0
    assert "no knowledge store" in result.output.lower()
