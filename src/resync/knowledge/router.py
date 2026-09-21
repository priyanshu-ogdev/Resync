"""The adaptive router: send each query to the cheapest retrieval path that can answer it.

Per docs/architecture.md#5-research-foundations--citations: adaptive/router RAG is the 2026
production consensus over any single fixed pipeline. Phase 1 deliberately keeps this a simple heuristic,
not a learned classifier — see docs/implementation-plan.md#phase-1-knowledge-layer: a rule-based router is sufficient
for v0.1.0, and over-building it here would be exactly the kind of scope creep this project's design history repeatedly
flagged and corrected.
"""

from __future__ import annotations

import re
from enum import StrEnum

# A fully-qualified symbol looks like `module.sub.Class.method` — dots and identifier characters only,
# no spaces, and each segment must start with a letter or underscore (not a digit). Anything else is
# treated as a free-text question and gets full hybrid retrieval.
# Bug fix: the original `^[\w]+` allowed `\w` at position 0, which includes digits — so `123.something`
# would have routed to EXACT_SYMBOL_LOOKUP (a wasted DB round-trip with no results) instead of
# HYBRID_SEARCH. Python identifier rules require the first character be `[a-zA-Z_]`.
_SYMBOL_PATTERN = re.compile(r"^[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)+$")


class RetrievalRoute(StrEnum):
    EXACT_SYMBOL_LOOKUP = "exact_symbol_lookup"
    HYBRID_SEARCH = "hybrid_search"


def route(query: str) -> RetrievalRoute:
    """Exact-symbol queries (e.g. `peft.PeftModel.from_pretrained`) go to store.exact_symbol_lookup — a
    plain filter, no embedding call. This is the path the real-time gate's check_symbol_exists tool uses,
    since it must return before the calling agent's next token (docs/architecture.md#two-speeds).
    Everything else goes to store.hybrid_search, used by the scheduled sweep's free-text retrieval."""
    if _SYMBOL_PATTERN.match(query.strip()):
        return RetrievalRoute.EXACT_SYMBOL_LOOKUP
    return RetrievalRoute.HYBRID_SEARCH
