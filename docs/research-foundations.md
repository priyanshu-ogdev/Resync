# Research foundations

This document traces every retrieval, verification, and local-execution decision in `docs/architecture.md`
back to the specific paper, benchmark, or existing tool it came from. The point of writing this separately is
so a future contributor can tell the difference between "we chose this because a specific finding justified
it" and "we chose this because it seemed reasonable" — everything here is the former.

## 1. Why retrieval isn't a single technique

The naive "chunk, embed, retrieve top-k, stuff into prompt" pipeline is the floor of modern RAG, not the
target. One widely cited comparison found plain RAG answered only ~44% of factual queries correctly on a
benchmark corpus, while a stack combining hybrid retrieval, reranking, and better chunking reached ~63% on the
same corpus. Resync's knowledge layer is built from the specific techniques that close that gap:

- **Hybrid retrieval + reranking (the foundation).** Dense vectors and BM25 fused via reciprocal rank fusion,
  then a cross-encoder reranks the candidates. Every other technique below sits on top of this baseline.
- **Contextual Retrieval (Anthropic).** An LLM prepends a sentence of document-level context to each chunk
  before embedding, so an isolated chunk doesn't lose the "what file or version this came from" signal —
  directly relevant when a changelog snippet is meaningless without knowing which version pair it describes.
- **RAPTOR.** A recursive tree of cluster summaries, so a query can retrieve at the right altitude — useful
  when a question is about a whole migration guide rather than one function.
- **GraphRAG (Microsoft) and code-specific descendants (CodeRAG, CGM, dataflow-guided retrieval).** Communities
  of entities summarized into subgraphs, for "how does A relate to B" questions a flat chunk store can't
  answer — the direct ancestor of Resync's call/import graph.
- **Self-RAG / Corrective RAG (CRAG).** The model grades its own retrieved evidence and re-retrieves or
  abstains on low confidence, instead of always generating from whatever came back.
- **Agentic RAG.** Retrieval as a multi-step, model-driven loop (plan, retrieve, inspect, decide if more is
  needed) rather than one retrieve-then-generate pass — the ancestor of Resync's "reflect before patch" step.
- **Adaptive / router RAG.** A complexity classifier sends each query to the cheapest pipeline that can answer
  it. This is the 2026 production consensus pattern, and it's why Resync's real-time gate (a cheap lookup) and
  its scheduled semantic sweep (full retrieval) are architecturally separate paths, not one pipeline reused for
  everything.
- **PageIndex.** A vectorless, hierarchical table-of-contents style retrieval method for long structured
  documents. Reviewed and deliberately *not* adopted as Resync's primary retrieval mode — Resync's core content
  is structured knowledge records and changelogs, not long unstructured manuals, so a second retrieval engine
  wasn't justified. Worth revisiting if the knowledge base later ingests full compliance or standards documents.

## 2. Repository-level code retrieval (RACG)

Code retrieval for editing tasks has its own literature, organized around retrieval substrate (sparse, dense,
or graph), control regime (single-shot vs. agentic/iterative), and evaluation setting.

- **RepoCoder** — iterative retrieve-generate: a candidate edit becomes the next query, and the loop repeats.
  Informs Resync's bounded multi-attempt semantic-patch loop.
- **SWE-agent / AutoCodeRover** — a ReAct-style loop that judges whether newly retrieved context is sufficient
  before generating, rather than generating immediately. This reflection step is exactly what Resync's
  differential-equivalence layer exists to enforce mechanically rather than rely on the model to self-judge —
  see `docs/adr/0002-differential-equivalence-verification.md`.
- **Repoformer** — selective retrieval: the model learns to skip retrieval when it would only add noise, the
  code-generation analog of Resync's adaptive router.

## 3. Security-specific knowledge extraction: Vul-RAG

Rather than embedding raw vulnerable-code chunks, Vul-RAG has an LLM extract multi-dimensional knowledge from
each historical CVE — the code's functional purpose, the vulnerability's root cause, and the fix — and
retrieves against new code by *functional* similarity rather than lexical similarity. This mattered because
surface-level similarity is a poor signal for telling vulnerable code apart from a nearly-identical patched
version; the technique was validated by finding previously-unknown, real, CVE-assigned bugs in the Linux
kernel. This is the direct template for Resync's knowledge-record schema (`docs/architecture.md#knowledge-layer`):
a structured `old_symbol → new_symbol → rule_type → confidence` record, never a raw embedded chunk of prose.

## 4. Why the split is a client and a server, and why that server speaks MCP

MCP exists because of the N-by-M integration problem: without a shared protocol, every agent needs bespoke
code for every tool, and every tool needs bespoke code for every agent — a matrix that grows faster than any
team can maintain. A standard protocol collapses that matrix to N+M. This is why an early "virtual server that
returns context to a local client" design idea converged specifically on MCP rather than a bespoke REST API —
it is the already-adopted standard that Claude Code, Cursor, OpenCode, and Google Antigravity's tool layer all
speak, so building one server buys compatibility with all of them at once. Full detail on the protocol
revision this project builds against is in `docs/adr/0001-mcp-client-server-split.md`.

## 5. Local, low-VRAM execution research

- **4-bit weight quantization (GGUF, via llama.cpp)** is the standard way to fit a 7–14B model into consumer
  VRAM. llama.cpp specifically because it supports mixed CPU/GPU offload with tunable `--n-gpu-layers`, unlike
  GPU-only serving stacks.
- **KV-cache compression** is the other half of the VRAM budget, since context length is bounded by cache size,
  not just weights. TurboQuant (Google Research, ICLR 2026, arXiv:2504.19874) rotates activations before
  quantizing to neutralize the outliers that make naive KV quantization unstable, reaching 3–4 bits per value
  with near-zero measured accuracy loss. Tooling around it is still maturing (a `tqai` package, a CPU-focused
  `TurboQuantCPU` package, and an experimental, not-yet-upstreamed llama.cpp branch), so Resync's default is
  the already-shipped, stable equivalent — `--cache-type-k q4_0 --cache-type-v q4_0` — with the TurboQuant
  branch treated as a benchmarked upgrade path, not a default dependency.
- **Model choice**: Qwen2.5-Coder-7B-Instruct at Q4_K_M is the current standout for local coding work in the
  6–8GB tier, with the 14B variant fitting a 12GB budget; Devstral is a reasonable agentic-workflow alternative
  when tool-use reliability matters more than raw code quality.
- **Embeddings**: `fastembed` (Qdrant-maintained, ONNX Runtime-based) runs `nomic-ai/nomic-embed-text-v1.5`
  without pulling in PyTorch or the Transformers dependency chain — a real, cited design goal of the library.
  This matters specifically here: the coding model needs the 6–12GB VRAM budget, so the embedding step
  shouldn't compete for any of it or bloat install size for a CPU-only knowledge server. See
  `docs/tech-stack.md`.

## References

- ARAGOG and related hybrid-RAG accuracy comparison studies (naive RAG ~44% → hybrid+rerank ~63% on a shared
  benchmark corpus).
- Anthropic, "Contextual Retrieval" (2024).
- RAPTOR (recursive abstractive tree retrieval).
- GraphRAG (Microsoft) and code-specific descendants (CodeRAG, CGM, dataflow-guided retrieval).
- Self-RAG / Corrective RAG (CRAG).
- PageIndex (vectorless, hierarchical tree retrieval for long structured documents).
- RepoCoder, SWE-agent, AutoCodeRover, Repoformer — repository-level code retrieval and agentic editing
  research.
- Vul-RAG — knowledge-level RAG for vulnerability detection, validated against real Linux kernel bugs.
- TurboQuant (Google Research, ICLR 2026, arXiv:2504.19874).
- fastembed (Qdrant) — ONNX-based embedding library, ships `nomic-embed-text-v1.5` support natively.
