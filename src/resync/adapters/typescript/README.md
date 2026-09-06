# `adapters/typescript/`

Wraps the TypeScript Compiler API for `extract_api_diff` (diffing the public `.d.ts` surface between two
installed versions — the same technique Microsoft's own API Extractor tool uses) and ast-grep for
`structural_patch`. See `docs/multi-language-adapters.md#typescript`. Not required for the initial milestone —
see the build-priority table in `docs/architecture.md`.
