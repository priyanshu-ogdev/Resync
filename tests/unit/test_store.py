"""Per docs/testing-strategy.md. These specifically regression-test the two bugs caught in the Phase 1
review pass: unescaped filter-string interpolation, and the old_symbol/parameter conflation. Written to run
without a live LanceDB connection (monkeypatching the embedding call), since _to_row/_from_row/
_escape_sql_literal are pure logic that doesn't need one.
"""

from resync.knowledge import store
from resync.knowledge.embeddings import EMBEDDING_DIM
from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType


def _fake_embed(_text: str) -> list[float]:
    return [0.0] * EMBEDDING_DIM


def test_escape_sql_literal_doubles_single_quotes() -> None:
    assert store._escape_sql_literal("O'Brien") == "O''Brien"


def test_escape_sql_literal_leaves_normal_strings_untouched() -> None:
    clean = "peft.PeftModel.from_pretrained"
    assert store._escape_sql_literal(clean) == clean


def test_round_trip_parameter_level_change(monkeypatch) -> None:
    monkeypatch.setattr(store, "embed_document", _fake_embed)
    record = KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.PreTrainedModel.from_pretrained",
        new_symbol="transformers.PreTrainedModel.from_pretrained",
        parameter="use_auth_token",
        new_parameter="token",
        from_version="<4.32.0",
        to_version=">=4.32.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.98,
    )
    assert store._from_row(store._to_row(record)) == record


def test_round_trip_whole_symbol_removal_with_no_replacement(monkeypatch) -> None:
    monkeypatch.setattr(store, "embed_document", _fake_embed)
    record = KnowledgeRecord(
        package="somepkg",
        ecosystem="pypi",
        old_symbol="somepkg.old_func",
        new_symbol=None,
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.REMOVED_NO_REPLACEMENT,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.9,
    )
    assert store._from_row(store._to_row(record)) == record


def test_round_trip_reorder_record(monkeypatch) -> None:
    """Added alongside REORDER support (patch/ast_grep_runner.py) — the LanceDB row schema must be kept in
    sync with KnowledgeRecord whenever the domain model grows a field, or the storage layer silently drops
    data the domain model claims to support."""
    monkeypatch.setattr(store, "embed_document", _fake_embed)
    record = KnowledgeRecord(
        package="netlib",
        ecosystem="pypi",
        old_symbol="netlib.connect",
        new_symbol="netlib.connect",
        old_param_order=["host", "port"],
        new_param_order=["port", "host"],
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.REORDER,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.9,
    )
    assert store._from_row(store._to_row(record)) == record


def test_upsert_escapes_quotes_in_the_delete_filter(monkeypatch) -> None:
    """Regression test for the real bug: a symbol containing a single quote must not break, or alter, the
    delete filter LanceDB receives."""
    monkeypatch.setattr(store, "embed_document", _fake_embed)
    captured_filters: list[str] = []

    class FakeTable:
        def delete(self, filter_str: str) -> None:
            captured_filters.append(filter_str)

        def add(self, rows: list[dict]) -> None:
            pass

    record = KnowledgeRecord(
        package="pkg",
        ecosystem="pypi",
        old_symbol="pkg.func_with_a_quote's_name",
        new_symbol="pkg.fixed_name",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.9,
    )
    store.upsert(FakeTable(), [record])
    assert "func_with_a_quote''s_name" in captured_filters[0]
    assert "func_with_a_quote's_name" not in captured_filters[0]
