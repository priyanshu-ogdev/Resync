# `tests/fixtures/`

Small, real repos with a known, deliberately introduced breaking change each — used to test the full
detect → retrieve → patch → verify loop end to end, not mocked.

Naming convention: `<package>-<change-type>/`, e.g. `peft-param-split/`, `bitsandbytes-removed-symbol/`. Each
fixture directory should include a short `NOTES.md` stating exactly what was changed, between which two
versions, and what the correct fix looks like — this doubles as the ground truth the differential-equivalence
layer's test-generation is checked against during development.
