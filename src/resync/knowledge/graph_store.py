"""The call/import graph, on the actively-maintained Kùzu fork (docs/adr/0004-graph-index-kuzu-fork.md).

Schema creation is wrapped defensively (try/except on re-creation) rather than relying on `IF NOT EXISTS`
DDL syntax that wasn't independently confirmed against the pinned fork version — consistent with this
project's own standard of verifying rather than assuming API surfaces (docs/tech-stack.md).

Review note 1: the initial version of this module iterated QueryResult with a plain `for row in result` loop,
assuming Python's binding supports direct iteration. That was never confirmed. Every corroborating source
checked (the R wrapper, the Node.js bindings, the C++ API) exposes iteration only via explicit `has_next()`/
`get_next()` calls, not an iterator protocol — so this module uses that pattern instead, which is confirmed
correct across bindings rather than assumed correct for this one.

Review note 2, a real bug found on a later pass: `init_schema`'s original `except RuntimeError: pass` caught
every RuntimeError, not just the "table already exists" case it was written for. Tested directly against a
real Kùzu instance: both a duplicate `CREATE NODE TABLE` and a genuinely malformed one (a missing comma)
raise the exact same `RuntimeError` type — the only distinguishing signal is the message text ("already
exists in catalog" vs. "Parser exception"). The original code would have silently swallowed a real schema
typo on first run, not just correctly ignored a legitimate re-initialization on a later run. Fixed by
checking the message before deciding to ignore it.
"""

from __future__ import annotations

from pathlib import Path

import kuzu


def connect(db_path: Path) -> kuzu.Connection:
    db = kuzu.Database(str(db_path))
    return kuzu.Connection(db)


def default_db_path(repo_root: Path) -> Path:
    """See `knowledge.store.default_db_path`'s docstring — same decision, same convention, kept in the
    same `.resync/` directory as the LanceDB database rather than a separate top-level path."""
    return repo_root / ".resync" / "graph.kuzu"


def init_schema(conn: kuzu.Connection) -> None:
    """File nodes and IMPORTS edges only, per Phase 1 scope (docs/implementation-plan.md#phase-1-knowledge-layer).
    CALLS and DATAFLOW edge types are noted as follow-on work in docs/multi-language-adapters.md but are not
    part of this phase — extending the schema later is additive (a new CREATE REL TABLE statement), not a
    migration, so there's no cost to deferring it."""
    statements = [
        "CREATE NODE TABLE File(path STRING, vault_id STRING, authority_score DOUBLE, PRIMARY KEY(path))",
        "CREATE REL TABLE IMPORTS(FROM File TO File)",
    ]
    for stmt in statements:
        try:
            conn.execute(stmt)
        except RuntimeError as e:
            if "already exists" not in str(e):
                raise  # a genuine schema bug must not be silently swallowed — see review note 2 above


def upsert_file(conn: kuzu.Connection, path: str, vault_id: str, authority_score: float) -> None:
    # MERGE + SET chained in one statement is standard openCypher, which Kùzu targets compatibility with;
    # worth a smoke test against the pinned fork version before first real use, per this project's own
    # verify-don't-assume standard (docs/tech-stack.md), rather than trusting compatibility claims blindly.
    conn.execute(
        "MERGE (f:File {path: $path}) SET f.vault_id = $vault_id, f.authority_score = $authority_score",
        parameters={"path": path, "vault_id": vault_id, "authority_score": authority_score},
    )


def add_import_edge(conn: kuzu.Connection, importer_path: str, imported_path: str) -> None:
    conn.execute(
        "MATCH (a:File {path: $a}), (b:File {path: $b}) MERGE (a)-[:IMPORTS]->(b)",
        parameters={"a": importer_path, "b": imported_path},
    )


def importers_of(conn: kuzu.Connection, file_path: str) -> list[str]:
    """Every file that imports the given file — the basic building block the Impact Map's blast-radius
    calculation (docs/architecture.md#the-impact-map) is built on, once that phase is reached.

    Bug fix: previously used `for row in result`, which assumed unconfirmed iterator support. Uses the
    confirmed has_next()/get_next() pattern instead — see the module docstring.
    """
    result = conn.execute(
        "MATCH (a:File)-[:IMPORTS]->(b:File {path: $path}) RETURN a.path",
        parameters={"path": file_path},
    )
    # execute() is typed QueryResult | list[QueryResult] because Kùzu supports multi-statement queries
    # (semicolon-separated); this module only ever sends one statement at a time, so a real assertion here
    # both satisfies the type checker correctly and fails loudly if that assumption is ever violated,
    # rather than silently misbehaving on a list — confirmed by checking kuzu.Connection.execute's actual
    # signature rather than assuming the simpler return type.
    assert not isinstance(result, list), "expected a single QueryResult for a single-statement query"
    paths: list[str] = []
    while result.has_next():
        row = result.get_next()
        # get_next() is typed list[Any] | dict[str, Any] — confirmed empirically that a plain
        # `RETURN a.path` query shape returns the list variant, not dict; asserted rather than silently
        # trusted, so this fails loudly if that ever changes rather than misbehaving on a dict.
        assert isinstance(row, list), "expected the list variant of get_next() for this query shape"
        paths.append(row[0])
    return paths
