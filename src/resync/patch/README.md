# `patch/`

The deterministic-first patch layer. See `docs/adr/0003-deterministic-first-patching.md` for why mechanical
changes never touch the local model.

- `taxonomy.py` (add here) — the `RuleType`-driven classifier deciding mechanical vs. semantic handling; the
  enum itself lives in `knowledge/schema.py` since it's part of the KnowledgeRecord, but the classification
  logic belongs here.

Mechanical fixes (`RuleType.is_mechanical`) are applied via `ast-grep`, installed as a standalone binary, not a
Python binding — see `docs/tech-stack.md` for why.
