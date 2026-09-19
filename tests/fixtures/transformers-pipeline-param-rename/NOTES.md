# transformers-pipeline-param-rename

**Real, live-confirmed rename** (found and verified while debugging `knowledge/extract_api_diff.py`, not a
synthetic example): between `transformers` 4.31.0 and 4.32.0, `transformers.pipelines.pipeline`'s
`use_auth_token` keyword parameter was renamed to `token` — confirmed at the exact same positional index
(9) in both signatures, so this is an unambiguous rename, not the kind of coincidental-position/wrong-name
case documented in `tests/fixtures/peft-param-rename/NOTES.md`.

- **Before (transformers <= 4.31.0)**: `pipeline(..., use_auth_token=hf_token)`
- **After (transformers >= 4.32.0)**: `pipeline(..., token=hf_token)`
- **Correct fix**: rewrite the `use_auth_token=` keyword argument to `token=` on any call to `pipeline`.

`sample.py` uses the **old** name — matching `resync sync`'s mechanical tier should rewrite it to `token=`.
Ground truth confirmed via `resync.adapters.python.extract_api_diff.extract("transformers", "4.31.0", "4.32.0",
"4.31.0", "4.32.0")`, which detects this exact rename with confidence 0.78 among 1516 real records for this
version pair — see `tests/integration/test_extract_api_diff.py`.
