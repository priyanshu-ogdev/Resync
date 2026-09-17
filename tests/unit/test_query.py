"""Confirms find_knowledge dispatches to the correct store function based on the router's decision —
using fakes so this stays a unit test (no live LanceDB/embedding call needed)."""

from resync.knowledge import query


def test_exact_symbol_query_dispatches_to_exact_lookup(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(query, "exact_symbol_lookup", lambda table, q: calls.append(("exact", q)) or [])
    monkeypatch.setattr(query, "hybrid_search", lambda table, q, limit=5: calls.append(("hybrid", q)) or [])

    query.find_knowledge(table=object(), query_str="peft.PeftModel.from_pretrained")

    assert calls == [("exact", "peft.PeftModel.from_pretrained")]


def test_free_text_query_dispatches_to_hybrid_search(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(query, "exact_symbol_lookup", lambda table, q: calls.append(("exact", q)) or [])
    monkeypatch.setattr(query, "hybrid_search", lambda table, q, limit=5: calls.append(("hybrid", q)) or [])

    query.find_knowledge(table=object(), query_str="why was use_auth_token deprecated?")

    assert calls == [("hybrid", "why was use_auth_token deprecated?")]
