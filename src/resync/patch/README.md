# `patch/`

The deterministic-first patch layer. See `docs/adr/0003-deterministic-first-patching.md` for why mechanical
changes never touch the local model.

- `taxonomy.py` — `classify()`, deciding `PatchStrategy.MECHANICAL` / `SEMANTIC` / `ESCALATE` for a
  `KnowledgeRecord`. More than `RuleType.is_mechanical` alone: also checks confidence against
  `resync.toml`'s configurable threshold. Malformed records can't reach this function in the first place —
  `KnowledgeRecord`'s own pydantic validator (`knowledge/schema.py`) rejects a RENAME with no real target or
  a REORDER that isn't a true permutation at construction time.
- `ast_grep_runner.py` — wraps the real `ast-grep` CLI binary via subprocess. **Read this file's module
  docstring before touching it.** Four review passes against the real binary found ten distinct issues —
  grep-style exit codes, a keyword-argument parsing ambiguity, `--json`/`-U` not composing, whole-symbol
  renames needing a second import-statement rule, a cleaner YAML-rule replacement for the original
  placeholder-pattern hack, a missing `$$$REST` catch-all that silently broke REORDER on any call with extra
  arguments, REORDER's fundamental non-idempotency, an active **data-loss bug** where renaming one name on a
  multi-name import line silently deleted the others, a language-name mapping landmine for future non-Python
  adapters, and a **namesake-collision false-positive risk** now partially closed by an import-guard
  pre-check. All ten are documented in place specifically because they're each individually easy to silently
  reintroduce without re-running `tests/integration/test_ast_grep_runner.py`.

Mechanical fixes (`RuleType.is_mechanical`, above the confidence threshold) are applied via `ast-grep`,
installed as a standalone binary, not a Python binding — see `docs/tech-stack.md` for why.
