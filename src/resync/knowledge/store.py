"""LanceDB binding for KnowledgeRecord: hybrid (vector + BM25) retrieval with RRF fusion.

API verified against current LanceDB docs (lancedb.pydantic.LanceModel/Vector, the explicit
`.search(query_type="hybrid").vector(...).text(...)` pattern for externally-computed embeddings, and
RRFReranker confirmed as the library's own default hybrid reranker) rather than assumed from memory — see
docs/architecture.md#5-research-foundations--citations
for why hybrid + RRF is the retrieval foundation this project builds on.

This file went through one review-and-fix pass after the initial implementation. Two real bugs were caught
and fixed here, not just noted: (1) filter strings built via raw f-string interpolation of untrusted values
(symbol/package names) with no escaping — LanceDB's `.where()`/`.delete()` take a raw SQL-like predicate
string with no parameter binding, so this needed an explicit escaping helper, not a different API; and
(2) `exact_symbol_lookup` returned a single `Optional[KnowledgeRecord]`, silently dropping data for symbols
with more than one associated record (e.g. two different parameters renamed across two version pairs).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import lancedb
from lancedb.pydantic import LanceModel, Vector
from lancedb.rerankers import RRFReranker

from resync.knowledge.embeddings import EMBEDDING_DIM, embed_document, embed_query
from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType

TABLE_NAME = "knowledge_records"


def default_db_path(repo_root: Path) -> Path:
    """Where the LanceDB database lives for a given target repo, by default.

    Previously undecided entirely — no code or doc anywhere in this project had picked a location, which
    `server/tools.py`'s `check_symbol_exists` needed a real answer to in order to call `connect()` at all.
    `.resync/knowledge.lancedb`, mirroring the `.git`-directory convention (tool-local state living inside
    the repo it concerns, not some global cache path that would silently mix data across projects). This is
    a default, not a hard-coded path — a future `resync.toml` `[project]` field to override it is a
    reasonable follow-up, not assumed necessary yet since nothing has needed it so far.
    """
    return repo_root / ".resync" / "knowledge.lancedb"


def _escape_sql_literal(value: str) -> str:
    """Escape a value for interpolation into a LanceDB filter predicate string.

    LanceDB's `.where()`/`.delete()` take a raw SQL-like WHERE-clause string with no parameter-binding API
    (unlike Kùzu's Cypher `parameters={...}` — see graph_store.py). Doubling embedded single quotes is the
    standard SQL-literal escape; this is the fix for a real bug where a symbol or package name containing a
    quote would break, or manipulate, the filter.
    """
    return value.replace("'", "''")


class _KnowledgeRecordRow(LanceModel):
    """The LanceDB-native mirror of KnowledgeRecord. Kept as a separate class rather than making
    KnowledgeRecord itself a LanceModel: KnowledgeRecord is the domain schema used everywhere in this
    codebase (docs/architecture.md#knowledge-layer); this is purely a storage-layer concern (the vector
    column and the FTS-indexed search_text column don't belong on the domain model). Optional domain fields
    are stored as empty strings/lists, not nulls — LanceModel/Arrow round-tripping of Optional columns wasn't
    independently verified, and empty-as-sentinel is a known-safe pattern given _from_row/_to_row handle the
    conversion explicitly in one place.

    old_param_order/new_param_order were added alongside KnowledgeRecord's REORDER support — kept in sync
    with the domain schema deliberately, since letting the storage layer silently drop fields the domain
    model added would be exactly the kind of quiet data loss this project exists to catch in other tools.
    """

    package: str
    ecosystem: str
    old_symbol: str
    new_symbol: str
    parameter: str
    new_parameter: str
    old_param_order: list[str]
    new_param_order: list[str]
    from_version: str
    to_version: str
    rule_type: str
    source: str
    confidence: float
    search_text: str
    vector: Vector(EMBEDDING_DIM)  # type: ignore[valid-type]


def _to_row(record: KnowledgeRecord) -> dict[str, Any]:
    if record.old_param_order and record.new_param_order:
        change_desc = f"argument order {record.old_param_order} -> {record.new_param_order}"
    elif record.parameter:
        change_desc = f"parameter {record.parameter} -> {record.new_parameter}"
    else:
        change_desc = f"{record.old_symbol} -> {record.new_symbol or '(removed, no replacement)'}"
    search_text = (
        f"{record.package}: {record.old_symbol}: {change_desc} "
        f"between {record.from_version} and {record.to_version} ({record.rule_type.value})"
    )
    return {
        "package": record.package,
        "ecosystem": record.ecosystem,
        "old_symbol": record.old_symbol,
        "new_symbol": record.new_symbol or "",
        "parameter": record.parameter or "",
        "new_parameter": record.new_parameter or "",
        "old_param_order": record.old_param_order or [],
        "new_param_order": record.new_param_order or [],
        "from_version": record.from_version,
        "to_version": record.to_version,
        "rule_type": record.rule_type.value,
        "source": record.source.value,
        "confidence": record.confidence,
        "search_text": search_text,
        "vector": embed_document(search_text),
    }


def _from_row(row: dict[str, Any]) -> KnowledgeRecord:
    return KnowledgeRecord(
        package=row["package"],
        ecosystem=row["ecosystem"],
        old_symbol=row["old_symbol"],
        new_symbol=row["new_symbol"] or None,
        parameter=row["parameter"] or None,
        new_parameter=row["new_parameter"] or None,
        old_param_order=list(row["old_param_order"]) or None,
        new_param_order=list(row["new_param_order"]) or None,
        from_version=row["from_version"],
        to_version=row["to_version"],
        rule_type=RuleType(row["rule_type"]),
        source=RecordSource(row["source"]),
        confidence=row["confidence"],
    )


def connect(db_path: Path) -> lancedb.DBConnection:
    return lancedb.connect(str(db_path))


def get_or_create_table(db: lancedb.DBConnection) -> lancedb.table.Table:
    """Uses `list_tables().tables` rather than the deprecated `table_names()` — found via a
    DeprecationWarning during review, not caught by any test, since a deprecation warning doesn't fail a
    build until the method is actually removed. `table_exists()` looked like the more direct replacement but
    was checked first and rejected: it raises `NotImplementedError` for this local/embedded connection type,
    confirmed by actually calling it rather than assuming a same-named method behaves the same way across
    connection types.

    `create_index(config=FTS())` replaces the also-deprecated `create_fts_index` for the same reason —
    genuinely a little pointed, given this project exists to catch exactly this kind of deprecation drift in
    other people's code and had it sitting unnoticed in its own.
    """
    if TABLE_NAME in db.list_tables().tables:
        return db.open_table(TABLE_NAME)
    table = db.create_table(TABLE_NAME, schema=_KnowledgeRecordRow, mode="create")
    table.create_index("search_text", config=lancedb.index.FTS())
    return table


def _order_literal(order: list[str] | None) -> str:
    """Renders old_param_order/new_param_order as a LanceDB array-literal for filter predicates, e.g.
    ['host', 'port']. Confirmed against a real LanceDB table that list-column equality filtering with this
    literal syntax works for a *non-empty* list — but an empty array literal (`[]`) crashes the query
    planner outright (`concat requires input of at least one array`), confirmed by triggering it directly.
    Callers must not build a filter clause from this when `order` is empty — see upsert()."""
    items = ", ".join(f"'{_escape_sql_literal(v)}'" for v in (order or []))
    return f"[{items}]"


def upsert(table: lancedb.table.Table, records: list[KnowledgeRecord]) -> None:
    """Delete-then-add on the (package, old_symbol, parameter, [old_param_order], from_version, to_version)
    key.

    old_param_order is included in the key only when the record actually has one (REORDER records) — a real
    bug found in review: including `old_param_order = []` unconditionally, to distinguish REORDER records
    with different orderings, crashed LanceDB's query planner outright for every *other* record type, since
    they always have an empty old_param_order and `= []` isn't a valid comparison LanceDB can execute. This
    would have broken the very first upsert to a fresh table. Confirmed fixed by testing the RENAME,
    REMOVED_NO_REPLACEMENT, and REORDER cases together, not just the one the bug was found in.

    A dedicated merge_insert call would be a nicer single-step upsert; kept as delete-then-add here since
    that API's exact argument shape should be verified against the pinned lancedb version before relying on
    it (docs/tech-stack.md's general principle: verify against current install docs, don't assume). Every
    interpolated value is escaped via _escape_sql_literal — see that function's docstring for the bug this
    fixes.
    """
    for record in records:
        clauses = [
            f"package = '{_escape_sql_literal(record.package)}'",
            f"old_symbol = '{_escape_sql_literal(record.old_symbol)}'",
            f"parameter = '{_escape_sql_literal(record.parameter or '')}'",
            f"from_version = '{_escape_sql_literal(record.from_version)}'",
            f"to_version = '{_escape_sql_literal(record.to_version)}'",
        ]
        if record.old_param_order:
            clauses.append(f"old_param_order = {_order_literal(record.old_param_order)}")
        table.delete(" AND ".join(clauses))
    table.add([_to_row(r) for r in records])


def hybrid_search(table: lancedb.table.Table, query: str, limit: int = 5) -> list[KnowledgeRecord]:
    """Dense + BM25 fused with Reciprocal Rank Fusion — LanceDB's default hybrid reranker, and the
    foundation technique docs/architecture.md#5-research-foundations--citations identifies as the base
    every other retrieval technique in this project sits on top of. Vector and text are passed explicitly
    (rather than relying on a table-bound embedding function) since embeddings are computed externally
    via fastembed — this is LanceDB's documented pattern for exactly that case, not a workaround."""
    results = (
        table.search(query_type="hybrid")
        .vector(embed_query(query))
        .text(query)
        .rerank(reranker=RRFReranker())
        .limit(limit)
        .to_list()
    )
    return [_from_row(r) for r in results]


def all_records(table: lancedb.table.Table) -> list[KnowledgeRecord]:
    """Every record currently in the table, no filter/limit — the CLI's `resync sync` needs the full set to
    classify each one (patch/taxonomy.classify) rather than retrieve by query, unlike hybrid_search/
    exact_symbol_lookup above. A plain, unfiltered `search()` is LanceDB's own documented idiom for "give me
    every row" (there's no separate `.all()`/`.scan()` method on the table object)."""
    results = table.search().to_list()
    return [_from_row(r) for r in results]


def exact_symbol_lookup(table: lancedb.table.Table, old_symbol: str) -> list[KnowledgeRecord]:
    """The fast path the adaptive router (router.py) sends exact-symbol queries to — a plain filter, no
    embedding call, no reranking, so it stays fast enough to return before the calling agent's next token
    (docs/architecture.md#two-speeds).

    Returns every matching record, not just one — a symbol can have more than one associated
    KnowledgeRecord (e.g. two different parameters renamed across two different version pairs), and
    returning a single Optional silently dropped that information. The caller (server/tools.py's
    check_symbol_exists, once implemented) is responsible for narrowing by the project's actual pinned
    version.
    """
    results = table.search().where(f"old_symbol = '{_escape_sql_literal(old_symbol)}'").to_list()
    return [_from_row(r) for r in results]
