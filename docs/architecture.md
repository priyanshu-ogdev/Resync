# Resync — Architecture

This document is the technical companion to `README.md`. It states what the system is, why each component
exists, and what research or real-world prior art each decision traces back to. See `docs/workflow.md` for the
step-by-step runtime flow, and `docs/adr/` for the reasoning behind individual decisions in more depth.

## The problem

Two failure modes motivate this project:

**Old code rots.** Libraries deprecate and remove functions, and codebases accumulate calls into APIs no
longer present in the pinned version. The flagship example: a Python ML project on `peft` + `bitsandbytes` +
`transformers` + `torch` hits a decommissioned function or an incompatible CUDA/version combination — one of
the most common failure classes in ML development.

**New code is born broken.** Most code is now written through AI coding agents, and these agents have no live
knowledge of what's actually installed in a project's lockfile. They hallucinate package names at measured
rates — researchers call this **slopsquatting**, since attackers pre-register the hallucinated names with
malicious payloads. A USENIX Security 2025 study of 576,000 AI-generated code samples found 19.7% referenced
packages that don't exist at all; a 2026 follow-up on frontier models still found 4.6–6.1% hallucination rates,
with 58% of hallucinated names reproducing on a rerun of the same prompt. The same failure, one level down,
produces calls into deprecated or removed APIs valid in a model's training data but not in the pinned project.

No existing tool treats these as the same underlying problem — see the competitive landscape in
`docs/adr/0001-mcp-client-server-split.md` and `docs/adr/0002-differential-equivalence-verification.md` for
what was reviewed and why it falls short.

## Design principles

1. **Deterministic first, LLM only for the genuinely semantic fraction.** See `docs/adr/0003-deterministic-first-patching.md`.
2. **Never trust "the tests passed" as proof of correctness.** A 2026 study on LLM-generated refactorings found
   19–35% were functionally non-equivalent to the original, with ~21% of those undetected by the project's own
   existing test suite. A separate 2026 study found LLMs are unreliable at judging their own modernization
   output for exactly this kind of silent drift. See `docs/adr/0002-differential-equivalence-verification.md`.
3. **Prevention beats correction.** Every bug an agent is stopped from writing is cheaper than every bug fixed
   afterward.
4. **Guardrails live in the tool functions, not the prompt.** A call touching a pinned symbol is a hard,
   deterministic rejection inside the tool implementation — never something a model is merely instructed not to
   do. Adopted from how Google's Dependency Director enforces its own bot-author allowlist.

## System components

### Two speeds

- **Real-time prevention** — an MCP tool any agent calls before writing an import or installing a package:
  does this package exist, is it advisory-flagged, does this symbol exist in the pinned version. Must be a fast
  lookup, never an LLM call, so it returns before the agent's next token.
- **Scheduled correction** — risk-tiered, not one fixed cadence, to avoid the PR fatigue Dependabot/Renovate are
  known for: instant on a critical CVE or an agent-authored commit, daily for mechanical fixes, weekly for
  anything needing judgment.

### Knowledge layer

A structured knowledge record per change — not a raw embedded chunk of prose — following the template Vul-RAG
uses for vulnerability knowledge (extracting functional semantics, root cause, and fix from each CVE rather than
embedding raw text, which found previously-unknown, CVE-assigned bugs in the Linux kernel):

```
{ package, ecosystem, old_symbol, new_symbol, from_version, to_version,
  rule_type: rename | reorder | split | merge | return_shape_change |
             behavior_change | removed_no_replacement,
  source: compiler_warning | api_diff_tool | changelog_extract,
  confidence }
```

Retrieval is hybrid: dense + BM25 + reciprocal rank fusion (the documented foundation that takes a benchmark
corpus from roughly 44% to 63% factual accuracy over naive RAG), Contextual Retrieval-style context prepending
so an isolated chunk doesn't lose its version context, a call/import graph for structural relationships
(the GraphRAG pattern), and an adaptive router sending simple lookups to the fast path and escalating to full
agentic retrieval only when needed — the current production consensus rather than one fixed pipeline.

### Signature-change taxonomy

| Change type | Fix strategy | Verification needed |
|---|---|---|
| Rename only | Mechanical (ast-grep) | Compile check |
| Param reorder/rename | Mechanical | Compile check |
| Param split / merge | Semantic — a value must be derived | Differential equivalence |
| Return shape change | Semantic, propagates to every call site | Differential equivalence |
| Silent behavior change, same signature | Nothing to pattern-match | Deprecation-warning capture + differential fuzzing only |
| Removed, no replacement | No automatic fix is safe | Escalate to `resync.toml` |

### Trust and verification layer

For every change: static rule-match confidence, test-suite pass/fail (necessary, not sufficient), a
differential/property-based equivalence check (Hypothesis-generated inputs, old and new code paths compared
directly, or against an oracle derived from the retrieved knowledge record when the old version can't run
side-by-side, to avoid the circularity of testing a translation against itself), and a generator/critic
double-pass mirroring the Summary/Control/Code agent split used in the LADU research. These combine into a
decomposed trust score returned as structured MCP tool output.

### `resync.toml` — the compatibility contract

See the file at the repo root for the live, commented example. Pins and exceptions are checked *before* a
change is flagged, not after, so intentionally-frozen legacy code never becomes a false positive. Sync-vs-shift
decisions from the Impact Map (below) are persisted as `[[policy]]` entries so the same case isn't re-litigated.

### Deployment model

Resync is one MCP server; local (stdio) versus remote (Streamable HTTP) is a transport choice, not two designs.
Built against the 2026-07-28 stateless MCP core, which removed the old session-based handshake and deprecated
Roots/Sampling/Logging in favor of a model where a tool call needing input returns `resultType: "input_required"`
and is resent with the answer. Shipped alongside a companion Agent Skill for agents that support Skills but
haven't wired up the MCP server directly, per the current framing that MCP is the capability layer and Skills
are the know-how layer. See `docs/adr/0001-mcp-client-server-split.md`.

### Multi-language adapters

The core is language-agnostic; each language plugs in via `parse_manifest`, `resolve`, `extract_api_diff`,
`structural_patch`, `capture_deprecation_signals`. Adapters shell out to each ecosystem's native CLI tool
(`ast-grep`, `cargo-semver-checks`, `tsc`) rather than reimplementing per-language logic:

| Language | API-diff tool | Structural patch |
|---|---|---|
| Python | Custom `ast`/`inspect` diffing (no mature dedicated tool exists) | ast-grep |
| Rust | `cargo-semver-checks` | ast-grep, plus `cargo fix` for rustc-known migrations |
| TypeScript | TypeScript Compiler API (same technique as Microsoft's API Extractor) | ast-grep |
| Java (roadmap) | revapi / japicmp | ast-grep |
| Go (roadmap) | go-apidiff | ast-grep |

### Supply-chain provenance gate

Before landing any resolved version: check it against OSV.dev and the GitHub Advisory Database, and where
available its Sigstore signature or SLSA provenance attestation. An automated upgrader is itself a supply-chain
attack surface if it blindly trusts whatever a resolver picks.

### The Impact Map

When a signature change has no single obviously-correct propagation: build an impact map from the call/import
graph, cluster call sites by usage-pattern similarity using the anti-unification technique Facebook's Getafix
uses to mine fix patterns from a codebase's own commit history (which predicted the exact human-written fix as
the top suggestion in up to 91% of cases for some bug categories, in production at Facebook), and check for an
established local precedent before asking anyone anything. Only elicit a decision — via MCP's `input_required`
mechanism — when genuinely undecided. At scale, execute a confirmed "sync" the way Google's large-scale-change
infrastructure does: sharded into small, independently reviewable and revertible PRs rather than one diff, a
pattern proven at extreme scale by Google's own LLM-assisted 32-bit-to-64-bit integer migration, which cut a
two-year manual project in half with AI generating 70% of the changes.

## Build priority

| Priority | Scope | Status |
|---|---|---|
| 1 | Core loop on the Python/ML-stack niche | Must be fully working |
| 2 | Real-time MCP gate wired into at least one agent | Must be fully working |
| 3 | `resync.toml` pin/exception handling | Must be fully working |
| 4 | Supply-chain provenance check | Should be working |
| 5 | GitHub App wrapper, tiered scheduling | Nice to have |
| 6 | Multi-language adapters, Impact Map, manifest standard, benchmark | Roadmap only |

## References

- Spracklen et al., "We Have a Package for You! A Comprehensive Analysis of Package Hallucinations by Code
  Generating LLMs," USENIX Security 2025.
- 2026 frontier-model slopsquatting follow-up (Claude Sonnet 4.6, GPT-5.4-mini, Gemini 2.5 Pro, DeepSeek V3.2).
- 2026 study on functional non-equivalence in LLM-generated refactorings (19–35% non-equivalent, ~21% test-suite
  escape rate) and the companion "Articulate but Wrong" study on LLM self-review failure in code modernization.
- Anthropic, "Contextual Retrieval" (2024).
- Vul-RAG: knowledge-level RAG for vulnerability detection, evaluated against real Linux kernel bugs.
- RepoCoder, SWE-agent, AutoCodeRover, Repoformer — repository-level code retrieval and agentic editing research.
- Google, "Dependency Director" (Antigravity SDK + Gemini, July 2026) — closest reactive prior art.
- Facebook's Getafix — fix-pattern mining via hierarchical clustering and anti-unification, production-deployed.
- Google's large-scale-change (Rosie) infrastructure, and the LLM-assisted 32-bit-to-64-bit integer migration
  paper.
- TurboQuant (Google Research, ICLR 2026, arXiv:2504.19874) — KV-cache quantization; informs the local-execution
  design even though Resync defaults to the already-shipped llama.cpp equivalent.
- MCP specification revision, 2026-07-28 (stateless core).
- "Skills vs MCP: How AI Tools Have Evolved" — the capability/know-how framing behind shipping both an MCP
  server and a companion Agent Skill.
