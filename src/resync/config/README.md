# `config/`

`resync.toml` parsing, validation, and writing. See `docs/adr/0005-config-and-policy-persistence.md`.

- `schema.py` — the pydantic models: `ProjectConfig`, `ScheduleConfig`, `ConfidenceConfig`, `Pin`,
  `Exception_`, `Policy`, and the top-level `ResyncConfig` with `is_pinned_or_frozen` — the single check every
  other module must run *before* flagging a potential issue, not after.
- `loader.py` — `load` (stdlib `tomllib`, read-only) and `persist_policy` (via `tomli_w`, since the Impact Map
  needs to write confirmed decisions back into the file).
