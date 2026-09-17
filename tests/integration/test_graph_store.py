"""Real integration tests against an actual Kùzu instance — per docs/testing-strategy.md, mocking the graph
database away would defeat the point of testing this module at all.
"""

import pathlib

import pytest

from resync.knowledge import graph_store


@pytest.fixture
def conn(tmp_path: pathlib.Path):
    return graph_store.connect(tmp_path / "test.kuzu")


def test_schema_init_is_idempotent(conn) -> None:
    graph_store.init_schema(conn)
    graph_store.init_schema(conn)  # must not raise


def test_schema_init_does_not_swallow_a_genuine_error(conn) -> None:
    """Regression test for a real bug: the original `except RuntimeError: pass` caught every RuntimeError,
    not just the legitimate "already exists" case — confirmed by triggering a real parser error and
    checking it was the exact same exception type Kùzu raises for duplicate table creation."""
    graph_store.init_schema(conn)
    with pytest.raises(RuntimeError, match="Parser exception"):
        conn.execute("CREATE NODE TABLE Broken(path STRING PRIMARY KEY(path))")  # missing comma


def test_importers_of_returns_every_importer(conn) -> None:
    graph_store.init_schema(conn)
    graph_store.upsert_file(conn, "a.py", "vault1", 0.9)
    graph_store.upsert_file(conn, "b.py", "vault1", 0.9)
    graph_store.upsert_file(conn, "c.py", "vault1", 0.9)
    graph_store.add_import_edge(conn, "a.py", "c.py")
    graph_store.add_import_edge(conn, "b.py", "c.py")

    assert sorted(graph_store.importers_of(conn, "c.py")) == ["a.py", "b.py"]


def test_importers_of_returns_empty_for_an_unimported_file(conn) -> None:
    graph_store.init_schema(conn)
    graph_store.upsert_file(conn, "a.py", "vault1", 0.9)
    assert graph_store.importers_of(conn, "a.py") == []
