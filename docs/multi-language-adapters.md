# Multi-language adapters

The core (RAG, resolver invocation, sandboxing, trust scoring, PR generation, `resync.toml` handling) is
language-agnostic. Each supported language plugs in by implementing five functions. This document specifies
each function's contract and the concrete tool each adapter wraps to implement it — the design principle
throughout is "reuse an existing, purpose-built tool per ecosystem," never "reimplement per-language logic in
Resync itself."

## The adapter interface

```
parse_manifest(repo_path) -> list[Dependency]
    Read the ecosystem's lockfile/manifest into a normalized dependency list.

resolve(dependencies, target_profile) -> ResolvedLockfile
    Shell out to the ecosystem's native dependency resolver against a chosen profile
    (latest / pinned / security-only / date-based). Never reimplement a solver.

extract_api_diff(package, version_old, version_new) -> list[KnowledgeRecord]
    Produce the structured old_symbol -> new_symbol -> rule_type -> confidence records
    defined in docs/architecture.md#knowledge-layer.

structural_patch(file, knowledge_record) -> Diff
    Apply a mechanical fix via the shared ast-grep engine.

capture_deprecation_signals(test_run_output) -> list[DeprecationWarning]
    Parse the ecosystem's own compiler/runtime warning format for live drift signals.
```

## Python (primary, built for the flagship demo)

- `parse_manifest`: reads `pyproject.toml` / `requirements.txt` / lockfiles from `uv`, Poetry, or `pip-compile`.
- `resolve`: shells out to `uv` (preferred, fastest) or `pip-compile`/Poetry.
- `extract_api_diff`: custom `ast`/`inspect` diffing between two installed versions of a package. This is
  genuinely the hardest adapter to build well — no mature, dedicated API-diff tool exists for Python the way it
  does for the other three ecosystems below, which is worth stating plainly rather than glossing over.
- `structural_patch`: `ast-grep`.
- `capture_deprecation_signals`: Python's own `DeprecationWarning`/`FutureWarning` captured from a test run.

## Rust (second priority — genuinely the easiest, not a stretch goal)

- `parse_manifest`: `Cargo.toml` / `Cargo.lock`.
- `resolve`: `cargo update` / `cargo add --precise`.
- `extract_api_diff`: `cargo-semver-checks` — already outputs almost exactly the structured "what broke, why"
  record Resync's knowledge schema wants, so this adapter needs very little custom logic on top.
- `structural_patch`: `ast-grep` for general structural rewrites, plus `cargo fix` for the subset of changes
  rustc already knows how to auto-migrate (edition migrations and similar) — reuse it rather than duplicating
  that logic.
- `capture_deprecation_signals`: `#[deprecated]`-attribute compiler warnings from `cargo build`, or `cargo
  clippy` lints.

## TypeScript

- `parse_manifest`: `package.json` / lockfiles from npm, yarn, or pnpm.
- `resolve`: shells out to whichever of npm/yarn/pnpm the project already uses.
- `extract_api_diff`: the TypeScript Compiler API, diffing the public `.d.ts` surface between two installed
  versions — the same technique Microsoft's own API Extractor tool uses for exactly this purpose, so this is a
  validated approach, not a novel one.
- `structural_patch`: `ast-grep`, which already covers TS/TSX.
- `capture_deprecation_signals`: `@deprecated` JSDoc tags, which `tsc` already surfaces as compiler diagnostics
  without any extra parsing work.

## Java and Go (roadmap — designed, not built for the initial milestone)

- **Java**: `extract_api_diff` via `revapi` or `japicmp`, both of which compute API surface changes and
  classify them by source/binary/semantic compatibility. `structural_patch` via `ast-grep`.
- **Go**: `extract_api_diff` via `go-apidiff`, which compares exported API between revisions and outputs the
  required semver bump. `structural_patch` via `ast-grep`.

## Why this scope, and why the hackathon build stops at Rust and TypeScript

Per the build-priority table in `docs/architecture.md`, only the Python adapter is required for the flagship
demo; TypeScript and Rust are designed in this level of detail specifically so a reviewer or judge can see the
adapter interface generalizes rather than being hand-waved, without requiring their actual implementation
before the core loop and verification layer are solid. Adding Java or Go later means writing the same five
functions again — the interface itself does not need to change.
