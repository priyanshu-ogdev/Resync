# `knowledge/`

The structured knowledge-record schema and its retrieval layer. See `docs/architecture.md#5-research-foundations--citations` for why
this project follows Vul-RAG's approach — extracted, structured facts, not embedded raw prose — and
`docs/architecture.md#knowledge-layer` for the hybrid retrieval design (dense + BM25 + reciprocal rank fusion,
a call/import graph, and an adaptive router).

- `schema.py` — `KnowledgeRecord`, `RuleType` (the signature-change taxonomy), `RecordSource`.
- `store.py` — the LanceDB binding: hybrid vector+BM25 search fused with LanceDB's default RRF reranker, plus
  a fast exact-symbol-lookup path with no embedding call, used by the real-time gate. Real integration tests:
  `tests/integration/test_knowledge_store.py`, added after a review pass found `upsert()` would crash on the
  first write to any fresh table (an empty-array-literal filter comparison LanceDB's query planner can't
  execute), plus silently deprecated calls (`table_names()`, `create_fts_index()`) neither caught by any test.
- `graph_store.py` — the call/import graph on the Kùzu fork (`docs/architecture.md#decision-4-actively-maintained-kuzu-community-fork-for-graph-index`): `File` nodes and `IMPORTS`
  edges for Phase 1; `CALLS`/dataflow edges are noted as follow-on work, not built yet. Real integration
  tests: `tests/integration/test_graph_store.py`, including a regression test for an exception-handling bug
  that would have silently swallowed a genuine schema error, not just the intended "table already exists"
  case.
- `embeddings.py` — the `fastembed`/`nomic-embed-text-v1.5` wrapper (no `torch` anywhere in this module —
  see `docs/tech-stack.md`).
- `router.py` — the adaptive router: a simple heuristic (fully-qualified symbol → fast exact lookup,
  everything else → hybrid search) per `docs/implementation-plan.md#phase-1-knowledge-layer` — deliberately
  not a learned classifier for v0.1.0.
- `seed_data.py` — real, individually-cited knowledge records for the flagship demo packages. Deliberately
  small: see the module's own docstring for why this project won't bulk-generate plausible-looking "known"
  changes, and `tests/unit/test_seed_data.py` for the tests enforcing that discipline structurally.
