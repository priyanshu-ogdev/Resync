# `adapters/rust/`

Wraps `cargo-semver-checks` for `extract_api_diff` — it already outputs almost exactly the structured record
this project's knowledge schema wants, so this adapter needs the least custom logic of any language. Also
wraps `cargo fix` for the subset of changes rustc already knows how to auto-migrate. See
`docs/multi-language-adapters.md#rust`. Not required for the initial milestone.
