# Resync — Architecture & Technical Design

This document is the authoritative technical specification and design guide for Resync. It describes the system architecture, core design principles, foundational research, competitive differentiation, testing and release strategies, and the formal **Architectural Decisions & Rationale** governing each subsystem.

---

## 1. Problem Statement

Two distinct but converging failure modes motivate this project:

### Old Code Rots
Libraries deprecate, alter, and remove APIs across version boundaries. Over time, codebases accumulate calls into functions no longer present in their updated dependencies. In modern Python ML development—such as stacks combining `peft` + `bitsandbytes` + `transformers` + `torch`—a minor version bump routinely decommissioned vital functions or breaks CUDA compatibility, causing silent runtime failures and broken environments.

### New Code is Born Broken (Slopsquatting & AI Hallucinations)
Most code is now written or assisted by AI coding agents. These models have no live perception of what is actually installed in a project's lockfile, relying instead on stale training data. Consequently, agents hallucinate packages and APIs:
- **Slopsquatting Attack Surface**: A USENIX Security 2025 study of 576,000 AI-generated code samples found **19.7%** referenced packages that do not exist at all. Attackers exploit this by pre-registering hallucinated names with malicious payloads. A 2026 follow-up across frontier models (Claude Sonnet 4.6, GPT-5.4-mini, Gemini 2.5 Pro) still observed 4.6–6.1% package hallucination rates, with 58% of hallucinated names reproducing on prompt reruns.
- **Decommissioned API Hallucinations**: Even when package names are valid, models routinely invoke methods deprecated or removed in the pinned version.

Existing tools (Dependabot, Renovate) only bump version strings in lockfiles without repairing code. Resync unites real-time agent prevention with automated, verified repository self-healing.

---

## 2. Core Design Principles

1. **Deterministic First, LLM Only for Genuinely Semantic Shifts**: Apply structural AST replacements (`ast-grep`) wherever a signature transformation is mathematically unambiguous (renames, parameter reorders). Restrict local LLM invocation to complex semantic transformations (param split/merge, return shape changes).
2. **Never Trust "The Tests Passed" as Proof of Correctness**: Empirical research demonstrates that 19–35% of LLM-generated refactorings are functionally non-equivalent to the original, with ~21% slipping undetected through existing test suites. Furthermore, LLMs suffer from severe self-review blind spots ("Articulate but Wrong"). True verification demands differential, property-based equivalence checks.
3. **Prevention Beats Correction**: Intercepting an agent before it writes an invalid import or hallucinated function is orders of magnitude cheaper than diagnosing and repairing broken code in CI.
4. **Guardrails Live in Tool Code, Not System Prompts**: Advisory system prompt instructions ("do not touch pinned packages") fail unpredictably in long agent context windows. Pinned versions and security ceilings must be enforced as hard, deterministic rejections inside MCP tool execution.

---

## 3. System Architecture & Components

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   AI Coding Agents                                      │
│                (Cursor, Claude Code, Antigravity, VS Code, Zed, Windsurf)                │
└───────────────────────────────────────────┬─────────────────────────────────────────────┘
                                            │ MCP Protocol (stdio / Streamable HTTP)
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                Resync MCP Gateway Engine                                │
│  verify_package │ check_symbol_exists │ verify_patch_equivalence │ explain_change      │
└─────────────┬─────────────────────────────┬───────────────────────────────┬─────────────┘
              │                             │                               │
              ▼                             ▼                               ▼
    ┌──────────────────┐          ┌──────────────────┐            ┌──────────────────┐
    │ Knowledge Layer  │          │   Patch Engine   │            │   Verification   │
    │  (LanceDB Vector │          │  (ast-grep AST   │            │  (Differential,  │
    │   + Kùzu Graph   │          │   Rewriter +     │            │   Hypothesis,    │
    │   + FastEmbed)   │          │   Taxonomy)      │            │   Critic model)  │
    └──────────────────┘          └──────────────────┘            └──────────────────┘
              │                             │                               │
              └─────────────────────────────┼───────────────────────────────┘
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                               Repository State & Config                                 │
│          resync.toml (pins, expiring exceptions) │ 7 Language Manifests & AST           │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### Two Operational Speeds
- **Real-Time Prevention (Fast Gate)**: Deterministic MCP gateway (`verify_package`, `check_symbol_exists`, `verify_patch_equivalence`, `explain_change`, `get_compatibility_report`). Operates under a strict latency budget (<200ms target), executing static lookups against local indexes before an agent emits its next code token.
- **Scheduled Repository Sweep**: Risk-tiered background sweep (`resync check`, `resync sync`). Triages drift: immediate for critical CVEs or agent commits, daily for mechanical AST updates (`--tier mechanical`), and weekly for complex semantic migrations (`--tier semantic`).

### Structured Knowledge Layer
Rather than storing unstructured prose chunks, Resync extracts typed knowledge records following the Vul-RAG model:
```python
class KnowledgeRecord(BaseModel):
    package: str
    ecosystem: str
    old_symbol: str  # canonical symbol path without args
    new_symbol: str
    parameter: str | None = None
    new_parameter: str | None = None
    old_param_order: list[str] | None = None
    new_param_order: list[str] | None = None
    from_version: str
    to_version: str
    rule_type: RuleType  # rename, reorder, split, merge, return_shape_change, etc.
    source: RecordSource  # compiler_warning, api_diff_tool, changelog_extract
    confidence: float
```
Retrieval uses hybrid reciprocal rank fusion (BM25 + LanceDB dense vectors with FastEmbed `BAAI/bge-small-en-v1.5`), an in-process Cypher graph index ([`Vela-Engineering/kuzu`](https://github.com/Vela-Engineering/kuzu)), and an adaptive complexity router.

### Signature-Change Taxonomy & Patch Strategy
| Change Type | Fix Strategy | Verification Tier |
|:---|:---|:---|
| **Rename only** | Mechanical (`ast-grep`) | Tier 1 (Compile check) upgraded to Tier 2 (Deprecation differential) |
| **Parameter reorder** | Mechanical (`ast-grep` + `AppliedFix` ledger) | Tier 1 (Compile check) + Idempotency state guard |
| **Param split / merge** | Semantic (Local model synthesis) | Tier 3 (Hypothesis differential test) + Critic review |
| **Return shape change** | Semantic (Propagates to call sites) | Tier 3 (Differential check) + Adversarial critic pass |
| **Silent behavior change** | Semantic (Runtime warning capture) | Tier 2 (Deprecation capture) + Tier 3 (Differential check) |
| **Removed without replacement** | Manual escalation | Policy enforcement; records flagged as non-auto-fixable |

### Trust Scoring
Every proposed change receives a decomposed trust score across 4 dimensions:
- `rule_match`: Syntactic and AST structural confidence (0.0–1.0).
- `test_suite`: Project unit and integration test pass rate.
- `differential_equivalence`: Dual-execution input/output equivalence.
- `source_citation`: Reliability of upstream changelog/commit evidence.

---

## 4. Architectural Decisions & Rationale

<a id="decision-1"></a>
### Decision 1: Single MCP Server with Transport Duality
- **Context**: Resync must serve heterogeneous AI coding agents (Claude Code, Cursor, Antigravity, OpenCode, VS Code) in both single-developer local workflows and multi-developer shared environments. Bespoke integrations create an $N \times M$ maintenance crisis.
- **Decision**: Implement a single MCP server binary supporting two runtime transports:
  - `stdio`: Zero-latency local communication spawned by local agents.
  - `Streamable HTTP`: Shared team daemon running on Starlette/Uvicorn (`resync serve --transport streamable-http`).
  Target the **2026-07-28 stateless MCP specification core**, which replaces fragile stateful sessions with single-shot request/response and `resultType: "input_required"`. Pair with an Agent Skill (`skills/resync/SKILL.md`) for agents that rely on file-based capability discovery.
- **Alternatives Rejected**: Bespoke REST APIs per editor (unmaintainable); stdio-only (rules out team servers); stateful legacy MCP (deprecated).
- **Consequences**: Defensively built tools handle both single-user trusted execution and concurrent HTTP clients.

<a id="decision-2"></a>
### Decision 2: Differential Equivalence Over Test Passes
- **Context**: The traditional metric for automated refactoring tools—"existing tests pass"—fails in 19–35% of cases due to incomplete test suites and silent behavioral drift.
- **Decision**: Require differential, property-based equivalence verification before semantic patches are accepted. Using Hypothesis, Resync generates inputs targeting changed signatures, executes old and new paths side-by-side, and asserts identical output behavior. Where old code cannot run in parallel, synthetic oracles are derived from retrieved knowledge records. Semantic patches undergo an adversarial generator/critic double-pass (`LlamaServerCritic`).
- **Alternatives Rejected**: Trusting existing test suites alone (Dependency Director's flaw); unverified LLM self-review (vulnerable to hallucination).
- **Consequences**: Semantic fixes incur measurable compute and latency overhead to guarantee zero silent behavioral regressions.

<a id="decision-3"></a>
### Decision 3: Deterministic-First Patching
- **Context**: Routine migrations (renames, keyword argument shifts) have exact, deterministic solutions. Invoking LLMs for simple AST transforms introduces non-determinism, cost, and hallucination risk.
- **Decision**: Classify all changes via a strict signature taxonomy. Apply mechanical changes directly using tree-sitter-based `ast-grep` rules without invoking an LLM. Use local LLM generation only for semantic cases. Enforce `resync.toml` pins inside tool functions as immutable code constraints, not system prompt guidelines.
- **Alternatives Rejected**: Routing all transforms through LLMs; prompt-only safety instructions.
- **Consequences**: `ast-grep` is a mandatory core dependency. Parameter reordering requires explicit state tracking (`AppliedFix`) to maintain idempotency.

<a id="decision-4"></a>
### Decision 4: Actively-Maintained Kùzu Community Fork for Graph Index
- **Context**: Resync's knowledge layer and Impact Map require an embedded, in-process Cypher graph database. The original `kuzudb/kuzu` project was archived in October 2025 following Apple's acquisition of Kùzu Inc.
- **Decision**: Adopt the active community fork (`Vela-Engineering/kuzu`, maintained by Vela Partners). The fork retains embedded Cypher support, active maintenance, and introduces concurrent multi-writer capabilities required for multi-adapter monorepo scans. Memgraph is retained as an external server fallback.
- **Alternatives Rejected**: Remaining on the abandoned upstream `kuzudb/kuzu` (unmaintained security risk); Neo4j (heavyweight external daemon, commercial licensing).
- **Consequences**: Dependency risk is tied to an active single-company community fork.

<a id="decision-5"></a>
### Decision 5: `resync.toml` as the Single Source of Truth
- **Context**: Codebases require an auditable mechanism to freeze legacy code and persist migration decisions without perpetual false-positive warnings.
- **Decision**: Maintain a single root `resync.toml` declaring:
  - `[[pin]]`: Target version ceilings with mandatory human reasons.
  - `[[exception]]`: File- or symbol-level upgrade freezes with **mandatory `expires` dates** (to prevent permanent technical debt).
  - `[[policy]]`: Persisted sync-vs-shift decisions from the Impact Map.
  Checks execute *prior* to issue generation, eliminating false positives. Inline pragmas (`# resync: pin reason="..."`) provide granular, in-code overrides.
- **Alternatives Rejected**: Central cloud config service (breaks local version control); exceptions without expiry (creates unmonitored technical debt).
- **Consequences**: All scanner and verification paths must parse `resync.toml` on startup.

<a id="decision-6"></a>
### Decision 6: Declarative Registry for Multi-Agent Configuration
- **Context**: AI coding environments (Claude Desktop, Claude Code, Cursor, VS Code, OpenCode, Windsurf, Zed, Antigravity) use four fundamentally incompatible JSON config schemas and different file locations.
- **Decision**: Implement a declarative `ClientSpec` registry and generic `build_entry()` generator (`resync.cli.mcp_config`). Parameterize command style (`separate`, `array`, `nested_object`), root key (`mcpServers`, `servers`, `mcp`, `context_servers`), and env mapping. Support `resync mcp-config <client>`, `resync mcp-config-list` (with verification dates and bug notes), and a `resync mcp-config custom` escape hatch.
- **Alternatives Rejected**: Nested `if/elif` branches (unmaintainable); guessing unsettled config paths (risks corrupting client settings).
- **Consequences**: Adding support for new clients is a pure metadata configuration change.

---

## 5. Research Foundations & Citations

1. **Hybrid Retrieval & Reranking**: Naive vector RAG retrieves factual context accurately only ~44% of the time. Fusing dense embeddings with BM25 via Reciprocal Rank Fusion (RRF) and cross-encoder reranking lifts accuracy to ~63% (ARAGOG benchmark).
2. **Contextual Retrieval (Anthropic 2024)**: Document-level context is prepended to chunks before embedding, preserving version and library scope for short changelog snippets.
3. **Structured Security Knowledge (Vul-RAG)**: Extracting functional purpose, root cause, and remediation into structured records rather than raw prose chunks significantly boosts retrieval relevance and catches previously unknown vulnerabilities.
4. **Repository-Level Code Retrieval (RACG)**: Incorporates findings from RepoCoder (iterative retrieve-generate loops), AutoCodeRover/SWE-agent (ReAct-style reflection), and Repoformer (selective retrieval gating).
5. **Low-VRAM Local Execution**: 
   - Uses `fastembed` (ONNX Runtime, `BAAI/bge-small-en-v1.5`) for embedding generation, eliminating all PyTorch (`torch`) runtime dependencies from the core server.
   - Leverages llama.cpp with 4-bit quantization (Q4_K_M) for 7B/14B local models within a 6–12GB VRAM envelope, referencing TurboQuant (ICLR 2026, arXiv:2504.19874) for KV-cache rotation.

---

## 6. Prior Art & Competitive Landscape

| Tool / Project | Category | Mechanism | Resync Advantage |
|:---|:---|:---|:---|
| **Dependabot / Renovate** | Version Bumper | Opens PRs with version bumps in lockfiles; fails CI if breaking changes exist. | Resync actively patches broken call sites, verifies semantic equivalence, and prevents PR fatigue via risk-tiered scheduling. |
| **bump-pydantic / Codeshift** | Specific Codemods | Hand-written AST rules for single library migrations (e.g. Pydantic v1→v2). | Resync uses a generalized, polyglot `ast-grep` engine driven by dynamic knowledge records rather than hard-coded rules. |
| **Google Dependency Director** (July 2026) | Reactive Agent | Listens for failed bot PRs, invokes Gemini to iteratively rewrite code up to 3 times, sandboxed. | Resync operates **proactively** (intercepting agent calls before commit), runs fully offline ($0 marginal token cost), and verifies patches with differential testing rather than trusting test-suite passes. |
| **LADU / LAMB** | Academic Agent | Multi-agent Java migration bots consulting docs. | Prototypes without persistent knowledge stores; Resync provides incremental, cached knowledge records and multi-language support. |
| **DepsRAG** | Graph RAG | Graph Q&A across PyPI/npm dependencies. | Q&A only; DepsRAG cannot inspect or patch application code. |
| **Facebook Getafix** | Fix Mining | Mines past bug fixes using hierarchical clustering and anti-unification. | Resync adopts Getafix's anti-unification technique for blast-radius clustering in the Impact Map. |

---

## 7. Testing Strategy & Quality Pyramid

Testing Resync requires rigorous standards because the system's entire premise is that conventional testing is insufficient:

1. **Unit Tests (276 tests)**: Strict isolation exercising pure logic in `config`, `knowledge`, `patch`, `verification`, and `adapters`.
2. **Property-Based Tests (Hypothesis)**: Tests of the verification layer itself, generating adversarial inputs against `RuleType` classifiers, `TrustScore` calculations, and `resync.toml` parsing.
3. **Integration Tests (106 tests)**: Real subprocess execution against real binaries (`ast-grep`, `uv`, local LanceDB/Kùzu stores, and real stdio/HTTP MCP handshakes).
4. **Adversarial Security Tests**: Asserts correct rejection of slopsquatted package names, malicious lockfiles, and invalid Sigstore attestations.
5. **Latency Budget Enforcement**: Asserts that real-time MCP gateway tools return within strict latency targets (<200ms p95 on warm local caches).
6. **Code Quality Standards**: 100% compliance with `ruff check`, `ruff format`, and `mypy --strict` across all source modules.

---

## 8. Release & Publishing Strategy

- **Semantic Versioning**: Strict SemVer 2.0.0 (`v0.1.0`), driven by Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`).
- **PyPI Trusted Publishing**: Secure OIDC publishing via `pypa/gh-action-pypi-publish` with no permanent API tokens stored in repository secrets.
- **Verification Gate on Release**: Resync's own supply-chain provenance gate and `resync doctor` diagnostics must pass cleanly on clean-room runner environments before publication.
- **Distribution Packages**:
  - Python Package (`resync-mcp` on PyPI).
  - Standalone Single-Binary Installers: POSIX shell (`installer/install.sh`) and Windows native C executable (`installer/install.exe`).

---

## 9. Build Priority & Component Status

| Priority | Scope | Implementation Status |
|:---|:---|:---|
| **1** | Core loop on Python/ML-stack niche | **Fully Built & Verified** (`griffe`, `pip download`, `ast-grep`) |
| **2** | Real-time MCP gate (5 production tools) | **Fully Built & Verified** (stdio & Streamable HTTP) |
| **3** | `resync.toml` pin/exception engine | **Fully Built & Verified** (Pydantic TOML persistence, `AppliedFix` guard) |
| **4** | Supply-chain provenance gate | **Fully Built & Verified** (PEP 740 attestations + Sigstore) |
| **5** | Terminal UI & Starlette Review Dashboard | **Fully Built & Verified** (`rich` explainability cards, `/dashboard` web UI) |
| **6** | Polyglot Language Adapters (7 languages) | **Fully Built & Verified** (Python, Rust, TypeScript, Go, Kotlin, Java, C/C++) |

---

## 10. Consolidated Academic & Industry References

- Spracklen et al., *"We Have a Package for You! A Comprehensive Analysis of Package Hallucinations by Code Generating LLMs,"* USENIX Security 2025.
- *"Articulate but Wrong: Self-Review Failures in LLM-Based Code Modernization,"* 2026.
- Anthropic, *"Contextual Retrieval,"* 2024.
- Vul-RAG, *"Knowledge-Level RAG for Vulnerability Detection,"* evaluated on Linux kernel vulnerabilities.
- RepoCoder, SWE-agent, AutoCodeRover, Repoformer, *Repository-Level Code Retrieval and Agentic Refactoring Benchmarks*.
- Google, *"Dependency Director: Automated Dependency Repair with Gemini and Antigravity,"* July 2026.
- Bader et al., *"Getafix: How Facebook automatically fixes bugs for millions of developers,"* 2019.
- TurboQuant, *"Outlier-Neutralized KV-Cache Quantization,"* Google Research, ICLR 2026.
- Model Context Protocol (MCP) Specification Revision, July 28, 2026 (Stateless core).
