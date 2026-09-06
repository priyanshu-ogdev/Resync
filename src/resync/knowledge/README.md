# `knowledge/`

The structured knowledge-record schema and its retrieval layer. See `docs/research-foundations.md#3` for why
this project follows Vul-RAG's approach — extracted, structured facts, not embedded raw prose — and
`docs/architecture.md#knowledge-layer` for the hybrid retrieval design (dense + BM25 + reciprocal rank fusion,
a call/import graph, and an adaptive router).

- `schema.py` — `KnowledgeRecord`, `RuleType` (the signature-change taxonomy), `RecordSource`.

Retrieval implementation (LanceDB vector/FTS index, the Kùzu-fork graph index, the router) belongs here once
built — see `docs/tech-stack.md` for the specific dependencies and `docs/adr/0004-graph-index-kuzu-fork.md`
for the graph-store choice.
