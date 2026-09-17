"""The single entry point Phase 2+ should call — router dispatch, hidden behind one function.

Before this, a caller had to know to call router.route() and then pick the right store function itself.
That's an easy thing to get wrong (or duplicate slightly differently) in every future caller — the MCP gate,
the scheduled sweep, and Phase 2's taxonomy classifier all need to look up KnowledgeRecords, and they should
all go through the same dispatch logic rather than each reimplementing it.
"""

from __future__ import annotations

import lancedb

from resync.knowledge.router import RetrievalRoute, route
from resync.knowledge.schema import KnowledgeRecord
from resync.knowledge.store import exact_symbol_lookup, hybrid_search


def find_knowledge(table: lancedb.table.Table, query_str: str, limit: int = 5) -> list[KnowledgeRecord]:
    """Route `query_str` to the fast exact-lookup path or full hybrid search, and return every match.

    This is what Phase 2's taxonomy classifier and (later) the MCP gate's check_symbol_exists should call —
    not store.exact_symbol_lookup/store.hybrid_search directly, so the routing decision lives in exactly one
    place.
    """
    match route(query_str):
        case RetrievalRoute.EXACT_SYMBOL_LOOKUP:
            return exact_symbol_lookup(table, query_str)
        case RetrievalRoute.HYBRID_SEARCH:
            return hybrid_search(table, query_str, limit=limit)
