from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from resync.cli.main import app
from resync.knowledge import store
from resync.knowledge.seed_data import SEED_RECORDS


def _fake_embed(text: str) -> list[float]:
    return [0.0] * store.EMBEDDING_DIM


@pytest.fixture(autouse=True)
def mock_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "embed_document", _fake_embed)


def test_seed_fresh_repo(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["seed", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Seeded" in result.output

    db_path = store.default_db_path(tmp_path)
    assert db_path.exists()
    db = store.connect(db_path)
    table = store.get_or_create_table(db)
    records = store.all_records(table)
    assert len(records) == len(SEED_RECORDS)


def test_seed_idempotency_and_force(tmp_path: Path) -> None:
    runner = CliRunner()
    # First seed
    res1 = runner.invoke(app, ["seed", str(tmp_path)])
    assert res1.exit_code == 0

    # Second seed without force
    res2 = runner.invoke(app, ["seed", str(tmp_path)])
    assert res2.exit_code == 0
    assert "already contains" in res2.output or "Seeded" in res2.output

    db_path = store.default_db_path(tmp_path)
    db = store.connect(db_path)
    table = store.get_or_create_table(db)
    assert len(store.all_records(table)) == len(SEED_RECORDS)

    # Third seed with --force
    res3 = runner.invoke(app, ["seed", str(tmp_path), "--force"])
    assert res3.exit_code == 0
    assert "Seeded" in res3.output


def test_check_warns_on_empty_knowledge_store(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["legacy-pkg>=1.0"]\n')
    (tmp_path / "resync.toml").write_text(
        '[[pin]]\npackage = "legacy-pkg"\nmax_version = "99.0.0"\nreason = "frozen"\n'
    )
    (tmp_path / "sample.py").write_text("import legacy_pkg\nlegacy_pkg.old_call()\n")

    # Explicitly create an empty database table
    db_path = store.default_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = store.connect(db_path)
    store.get_or_create_table(db)

    runner = CliRunner()
    res = runner.invoke(app, ["check", str(tmp_path)])
    assert res.exit_code == 0
    assert "Knowledge store is unseeded or empty" in res.output

    # Now seed it
    runner.invoke(app, ["seed", str(tmp_path)])
    res_seeded = runner.invoke(app, ["check", str(tmp_path)])
    assert res_seeded.exit_code == 0
    assert "Knowledge store is empty" not in res_seeded.output


def test_sync_warns_on_empty_knowledge_store(tmp_path: Path) -> None:
    # Explicitly create an empty database table
    db_path = store.default_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = store.connect(db_path)
    store.get_or_create_table(db)

    runner = CliRunner()
    res = runner.invoke(app, ["sync", str(tmp_path), "--tier", "mechanical"])
    assert res.exit_code == 0
    assert "Knowledge store is unseeded or empty" in res.output
