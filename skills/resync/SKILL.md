---
name: resync
description: Use before writing an import, adding a dependency, or calling a library function whose behavior
  might have changed since the model's training data. Calls Resync's MCP tools to verify a package exists, is
  not advisory-flagged, and that a called symbol exists in the project's pinned version, before committing to
  the code.
---

# Resync

Before writing any new import or dependency addition, call `verify_package` with the package name and the
ecosystem (pypi, npm, crates, etc.). Before calling a function from an existing dependency, call
`check_symbol_exists` with the fully-qualified symbol name and the version pinned in the project's lockfile.

If either check flags an issue, do not write the broken code. Resync returns rich structured outputs:
1. `explanation`: In-depth root cause breakdown and migration context.
2. `trust_breakdown`: Decomposed verification trust scores across Rule Match, Synthetic Test Suite, Differential Equivalence, and Source Citations.
3. `options`: Four standardized, actionable choices for the user or agent:
   - **[⚡ Sync]**: Automatically rewrite the call site using the verified replacement or run `resync sync --apply`.
   - **[🔄 Shift]**: Suggest alternative library, migration path, or prompt for semantic rewrite.
   - **[📌 Pin]**: Freeze the current version in `resync.toml` to prevent modifications.
   - **[⏳ Exception]**: Record an explicit, documented exemption in `resync.toml`.
4. `markdown_display`: Pre-formatted Markdown badge and card. Include this directly in your user-facing response when reporting an API change or dependency status.

To inspect root causes in depth or provide an executive summary, use `explain_change` (for individual symbols or packages) or `get_compatibility_report` (for batch sweeps).

After drafting a rewrite or modernization of a call site affected by an API change, call
`verify_patch_equivalence` with `fully_qualified_symbol`, `old_source`, `new_source`, and `pinned_version`.
This provides a deterministic, execution-free AST verification against the knowledge store rather than relying
on self-assessment.

If a call touches a symbol declared in the project's `resync.toml` under `[[pin]]` or `[[exception]]`, treat
that as a hard stop, not a suggestion: do not attempt to "fix" pinned or intentionally-frozen code without
explicit user instruction to do so.

