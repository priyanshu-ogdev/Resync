from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from resync.cli.main import app
from resync.knowledge import store
from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType


def _fake_embed(text: str) -> list[float]:
    return [0.0] * store.EMBEDDING_DIM


def test_ingest_preview_mode_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(store, "embed_document", _fake_embed)

    record = KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.pipelines.pipeline",
        new_symbol="transformers.pipelines.pipeline",
        parameter="use_auth_token",
        new_parameter="token",
        from_version="4.31.0",
        to_version="4.32.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.85,
    )

    with patch("resync.adapters.python.extract_api_diff.extract", return_value=[record]):
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "transformers", "4.31.0", "4.32.0", "--repo", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "rename" in result.output
        assert "use_auth_token" in result.output
        assert "Preview mode only" in result.output

        # Verify no database write occurred in preview mode
        db_path = store.default_db_path(tmp_path)
        assert not db_path.exists()


def test_ingest_apply_persists_records(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(store, "embed_document", _fake_embed)

    record = KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.pipelines.pipeline",
        new_symbol="transformers.pipelines.pipeline",
        parameter="use_auth_token",
        new_parameter="token",
        from_version="4.31.0",
        to_version="4.32.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.85,
    )

    with patch("resync.adapters.python.extract_api_diff.extract", return_value=[record]):
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "transformers", "4.31.0", "4.32.0", "--apply", "--repo", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "Successfully upserted 1 record(s)" in result.output

        db_path = store.default_db_path(tmp_path)
        assert db_path.exists()
        db = store.connect(db_path)
        table = store.get_or_create_table(db)
        records = store.all_records(table)
        assert len(records) == 1
        assert records[0].parameter == "use_auth_token"
        assert records[0].new_parameter == "token"


def test_ingest_empty_diff_reports_no_changes(tmp_path: Path) -> None:
    with patch("resync.adapters.python.extract_api_diff.extract", return_value=[]):
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "requests", "2.31.0", "2.32.0", "--repo", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "No breaking changes found" in result.output


def test_ingest_extract_failure_exits_nonzero(tmp_path: Path) -> None:
    with patch("resync.adapters.python.extract_api_diff.extract", side_effect=RuntimeError("Pip download failed")):
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "nonexistent", "1.0", "2.0", "--repo", str(tmp_path)])

        assert result.exit_code == 1
        assert "Failed to extract API diff" in result.output
