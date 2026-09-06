# Competitive landscape

Every tool and research prototype below was reviewed specifically for this project. This document exists so
that "why doesn't X already solve this" has a specific, checkable answer instead of an assumption.

## Version-bump-only tools

**Dependabot, Renovate.** Open a PR bumping a version pin when a new release is available. Neither edits code:
if the new version introduces a breaking change, the PR simply fails CI and sits there. Both are also
well-known for PR fatigue at scale — a fixed schedule opening one PR per outdated dependency regardless of
urgency. Resync's risk-tiered scheduling (`docs/architecture.md#two-speeds`) is a direct response to this.

## Per-library deterministic codemods

**`bump-pydantic`, Codeshift.** Hand-written AST/LibCST rules for one specific, known migration (Pydantic
v1→v2 in `bump-pydantic`'s case). Deterministic and safe within their scope, but someone has to write every
rule by hand, per library, per version jump — they don't generalize. Resync's `ast-grep`-based patch layer
(`docs/adr/0003-deterministic-first-patching.md`) keeps the same safety property while using one polyglot
engine instead of a bespoke tool per library.

## Dependency knowledge-graph RAG

**DepsRAG.** Builds a knowledge graph of direct and transitive dependencies across PyPI, npm, Cargo, and Go,
and answers questions about that graph via RAG plus generated Cypher queries, falling back to web search when
the graph can't answer. Validates that the dependency-graph approach generalizes across ecosystems — but it is
Q&A-only. It tells you about your dependencies; it does not edit your code.

## Academic migration agents

**LADU (LLM Agents for Automated Dependency Upgrades).** Splits the work across a Summary Agent, a Control
Agent, and a Code Agent that consult a migration guide and localize/patch outdated library usages in a live
Java codebase, benchmarked against synthetic repos with major version jumps. The Summary/Control/Code split is
directly adopted in Resync's generator/critic verification pass
(`docs/adr/0002-differential-equivalence-verification.md`).

**LAMB (LLM-Assisted Migration Bot).** Targets a similar problem to LADU — migrating deprecated API calls using
rules derived purely from API documentation, without fine-tuning. Both are Java/Maven-focused research
prototypes, not shipped products, and neither is attached to a persistent, incrementally-updated knowledge
base — they re-derive migration rules from documentation each time rather than caching structured knowledge
records.

## ML-stack diagnostics

**`harmonia-ml`.** Diagnoses torch/transformers/CUDA/bitsandbytes version compatibility and suggests which
versions to install together. This is exactly the pain point motivating Resync's flagship demo — but Harmonia
stops at diagnosis. It tells a developer what's broken; it never touches the code that's calling the broken
API.

## General agentic coding tools

**GitHub Copilot Workspace, Amazon Q Developer transform, Codex CLI.** Powerful, general-purpose agentic coding
tools that can be pointed at a migration task manually. None maintains a persistent, version-aware knowledge
base — context about what changed between versions is re-derived from the model's general knowledge or
whatever is pasted into the session each time, and none of them verify behavioral equivalence beyond whatever
test suite already exists.

## Reactive dependency-fix agent: Google's Dependency Director

The closest real prior art, released July 2026 on the Antigravity SDK with Gemini. Worth documenting in detail
because the differences are Resync's sharpest differentiators:

- **What it does:** watches for PRs already opened by Dependabot or Renovate; when one goes red in CI, clones
  the repo, checks out the PR branch, and has Gemini iteratively patch the code to match the dependency change
  (bounded to 3 attempts before giving up), sandboxed via `sandbox-runtime`, self-reviewed with a code-quality
  skill before pushing the fix back to the same PR.
- **What it deliberately doesn't do:** it is purely reactive — it only ever acts on a PR a bot already opened,
  and never prevents an agent from writing the broken call in the first place. It has no persistent knowledge
  base; "what changed" is re-reasoned live by Gemini on every run rather than retrieved from a cached, auditable
  record. It relies entirely on the project's existing test suite passing as its correctness signal, with no
  differential-equivalence check.
- **What Resync adopted from it anyway, because it's simply good engineering:** the principle that guardrails
  belong in tool functions, not prompts (its bot-author allowlist is a hard check in code, not an instruction);
  and `sandbox-runtime` itself, reused directly rather than re-implemented, for wrapping any agent-driven shell
  execution.
- **One useful number:** its own published cost is roughly 6 cents per PR in cloud model tokens. Resync's
  marginal cost per fix is $0 after the one-time local hardware cost — a concrete comparator, not an abstract
  privacy argument.

## Adjacent, structurally similar problems reviewed from other domains

Not competitors in the dependency-tooling category, but genuinely different paradigms that solve a
structurally identical "propagate one change correctly and at scale" problem, reviewed specifically because
they informed the Impact Map design (`docs/architecture.md#the-impact-map`):

- **Facebook's Getafix** — mines a codebase's own git history of past human fixes via hierarchical clustering
  and anti-unification, rather than relying on an upstream changelog, predicting the exact human-written fix
  as the top suggestion in up to 91% of cases for some bug categories in production use.
- **Google's large-scale-change (Rosie) infrastructure** — shards one semantic change too large to submit
  atomically into many small, independently testable, owner-routed PRs rather than one sweeping diff.
- **Google's LLM-assisted 32-bit-to-64-bit integer migration** — a real, published account of using this
  approach at extreme scale, cutting a two-year manual project in half with AI generating 70% of the changes.

## The gap Resync fills

No reviewed tool combines a persistent, version-aware knowledge base; genuine behavioral-equivalence
verification; a real-time prevention gate against a named, measured attack class (slopsquatting); and an
explicit, auditable mechanism for the "we know it's deprecated but can't upgrade yet" case every real codebase
eventually hits.
