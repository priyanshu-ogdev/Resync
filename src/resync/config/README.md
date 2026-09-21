# `config/`

`resync.toml` parsing, validation, and writing. See `docs/architecture.md#decision-5-resynctoml-as-the-single-source-of-truth`.

- `schema.py` — the pydantic models: `ProjectConfig`, `ScheduleConfig`, `ConfidenceConfig`, `Pin`,
  `Exception_`, `Policy`, and the top-level `ResyncConfig` with `is_pinned_or_frozen` — the single check every
  other module must run *before* flagging a potential issue, not after.
- `loader.py` — `load` (stdlib `tomllib`, read-only) and `persist_policy` (via `tomli_w`, since the Impact Map
  needs to write confirmed decisions back into the file).

Real tests: `tests/integration/test_config_loader.py`, including loading the project's own root
`resync.toml` (not a synthetic fixture), the no-file default case, and a check that `persist_policy` doesn't
silently drop existing pins/exceptions when it writes a new policy. Known, documented cosmetic limitation
(not a correctness bug): `persist_policy`'s `tomli_w`-based output places empty `pin`/`exception` arrays
before `[project]` rather than matching the clean, hand-authored key ordering of the project's own
`resync.toml` — the file is valid and round-trips correctly, it just looks structurally different from a
hand-written one. Worth a custom TOML writer if this becomes a real user-facing complaint; not fixed now
since it doesn't affect correctness.
