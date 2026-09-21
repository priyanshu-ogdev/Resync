"""Real integration tests against an actual LanceDB instance — per
docs/architecture.md#7-testing-strategy--quality-pyramid, mocking the
vector store away would defeat the point of testing this module. Embeddings are monkeypatched (see
tests/unit/test_store.py for why: the real model host isn't reachable in every environment), but the table
creation, listing, insert, filter, and delete paths below are all real LanceDB calls.
"""

import pathlib

import pytest

from resync.knowledge import store
from resync.knowledge.embeddings import EMBEDDING_DIM
from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType


@pytest.fixture(autouse=True)
def _fake_embeddings(monkeypatch):
    monkeypatch.setattr(store, "embed_document", lambda text: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(store, "embed_query", lambda text: [0.0] * EMBEDDING_DIM)


def test_get_or_create_table_is_idempotent(tmp_path: pathlib.Path) -> None:
    """Regression coverage for a real bug: the original get_or_create_table used the deprecated
    table_names(), found via a DeprecationWarning that a passing test suite would never have surfaced on its
    own. Also confirms table_exists() would have been the wrong fix — it raises NotImplementedError for this
    connection type, discovered by actually calling it, not assumed."""
    db = store.connect(tmp_path)
    first = store.get_or_create_table(db)
    second = store.get_or_create_table(db)  # must reopen, not attempt to recreate
    assert first.name == second.name == store.TABLE_NAME


def test_upsert_and_exact_symbol_lookup_round_trip(tmp_path: pathlib.Path) -> None:
    db = store.connect(tmp_path)
    table = store.get_or_create_table(db)
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
    store.upsert(table, [record])

    results = store.exact_symbol_lookup(table, "transformers.PreTrainedModel.from_pretrained")
    assert len(results) == 1
    assert results[0].parameter == "use_auth_token"
    assert results[0].new_parameter == "token"


def test_upsert_replaces_rather_than_duplicates_on_reupsert(tmp_path: pathlib.Path) -> None:
    db = store.connect(tmp_path)
    table = store.get_or_create_table(db)
    record = KnowledgeRecord(
        package="pkg",
        ecosystem="pypi",
        old_symbol="pkg.func",
        new_symbol="pkg.func2",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.9,
    )
    store.upsert(table, [record])
    store.upsert(table, [record])  # re-upserting the same record must not duplicate it

    results = store.exact_symbol_lookup(table, "pkg.func")
    assert len(results) == 1


def test_reorder_records_with_different_orders_do_not_collide(tmp_path: pathlib.Path) -> None:
    """Regression test for the real gap found in review: the delete key originally didn't include
    old_param_order, so two different REORDER records for the same symbol and version pair would collide on
    upsert. Confirmed here against a real table, not just reasoned about."""
    db = store.connect(tmp_path)
    table = store.get_or_create_table(db)
    record_a = KnowledgeRecord(
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
    record_b = record_a.model_copy(update={"old_param_order": ["a", "b", "c"], "new_param_order": ["c", "b", "a"]})
    store.upsert(table, [record_a])
    store.upsert(table, [record_b])

    results = store.exact_symbol_lookup(table, "netlib.connect")
    assert len(results) == 2, "both REORDER records should coexist, not overwrite each other"
