# ADR 0003: Deterministic patching first; the LLM only handles the genuinely semantic fraction

**Status:** accepted

## Context

Many API-compatibility fixes are mechanical (a rename, a parameter reorder) and have exactly one correct
answer once the old-to-new mapping is known. Routing every fix through an LLM regardless of its actual
complexity adds hallucination risk, cost, and latency to changes that a deterministic tool can already handle
perfectly. Separately, guardrails that live only in a prompt (an instruction telling a model "don't touch
pinned packages") are advisory, not enforced — a well-documented weak point in agentic tool design.

## Decision

Classify every change by the signature-change taxonomy in `docs/architecture.md` before deciding how to fix it.
Rename and reorder/rename changes are applied directly via `ast-grep` (a polyglot, tree-sitter-based structural
search-and-rewrite tool whose own stated purpose is exactly this: helping a library's users adopt breaking
changes across a codebase) with no LLM call at all. Only param split/merge, return-shape changes, and other
genuinely semantic cases are drafted by the local model. Separately, enforce `resync.toml` pins and exceptions
as hard checks inside the relevant tool functions themselves — never as an instruction the model is merely
told to follow — adopting the same principle Google's Dependency Director uses for its own bot-author
allowlist.

## Alternatives considered

- **Route every fix through the LLM for consistency** — rejected: unnecessary hallucination risk and cost for
  changes that are already fully deterministic.
- **Prompt-level guardrails only** (telling the model about pins via system instructions) — rejected: advisory
  instructions can be ignored or overridden by conflicting context in a long agent session; a tool-level check
  cannot be talked around.

## Consequences

This requires maintaining the signature-change taxonomy classifier as a first-class, tested component, since
misclassifying a semantic change as mechanical would apply an unverified fix without the equivalence check ADR
0002 requires. It also means `ast-grep` becomes a hard dependency across every supported language rather than
an optional convenience — see the multi-language adapters table in `docs/architecture.md`.

## References

- ast-grep — polyglot, tree-sitter-based structural search-and-rewrite tool.
- Google's Dependency Director (July 2026) — source of the "guardrails in tools, not prompts" principle.
