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

If either check fails, do not write the code as originally planned. Use the structured result returned —
which includes the classified reason (nonexistent package, advisory-flagged, deprecated symbol, removed
symbol) and, where known, the correct replacement — to adjust the code before proceeding.

If a call touches a symbol declared in the project's `resync.toml` under `[[pin]]` or `[[exception]]`, treat
that as a hard stop, not a suggestion: do not attempt to "fix" pinned or intentionally-frozen code without
explicit user instruction to do so.
