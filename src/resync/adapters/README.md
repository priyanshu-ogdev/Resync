# `adapters/`

Per-language plugins. See `docs/multi-language-adapters.md` for the full specification of each language's
implementation and which existing ecosystem tool it wraps.

- `base.py` — the `LanguageAdapter` Protocol every adapter implements: `parse_manifest`, `resolve`,
  `extract_api_diff`, `structural_patch`, `capture_deprecation_signals`.
- `python/` — the primary adapter, built first for the flagship ML-stack demo.
- `typescript/` — wraps the TypeScript Compiler API and ast-grep.
- `rust/` — wraps `cargo-semver-checks`, `cargo fix`, and ast-grep.

Adding a new language means implementing `base.LanguageAdapter` and adding fixture tests under
`tests/fixtures/` — the core never needs to change.
