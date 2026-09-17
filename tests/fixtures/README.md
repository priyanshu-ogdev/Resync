# `tests/fixtures/`

Small, real repos with a known, deliberately introduced breaking change each — used to test the full
detect → retrieve → patch → verify loop end to end, not mocked.

Naming convention: `<package>-<change-type>/`, e.g. `transformers-pipeline-param-rename/`,
`peft-param-rename/`. Each fixture directory includes a short `NOTES.md` stating exactly what was changed,
between which two real versions, and what the correct fix looks like — this doubles as the ground truth
`tests/integration/test_full_loop.py` and the differential-equivalence layer's test-generation are checked
against. Not every fixture demonstrates a success case — `peft-param-rename/NOTES.md` documents a real,
known limitation in the rename-correlation heuristic on purpose, so the limitation stays visible and
regression-tested rather than silently disappearing.
