# `adapters/python/`

The primary, flagship adapter — see `docs/multi-language-adapters.md#python`. This is genuinely the hardest
adapter to implement well: unlike Rust (`cargo-semver-checks`) or TypeScript (the Compiler API), there is no
mature, dedicated API-diff tool for Python yet, so `extract_api_diff` here is custom `ast`/`inspect` diffing
between two installed versions of a package rather than a wrapped third-party tool.
