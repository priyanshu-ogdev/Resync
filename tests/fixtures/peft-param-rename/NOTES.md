# peft-param-rename — a real, confirmed *heuristic limitation*, kept intentionally, not a success case

**This fixture documents a genuine false positive in `_correlate_removed_parameter`'s name-similarity
heuristic, found by actually running the full loop against it — it is not a "the loop works end to end"
demo like the other fixtures in this directory.** Keeping it (rather than deleting the evidence) is
deliberate: it's the concrete case referenced in `extract_api_diff.py`'s own module docstring.

**What really happened, between real `peft` 0.10.0 and 0.12.0** (confirmed via griffe against both real
package sources):
- Old signature: `gather_params_ctx(module, modifier_rank=0)`
- New signature: `gather_params_ctx(param, modifier_rank=0, fwd_module=None)`

The parameter at position 0 was renamed `module` → `param`. Separately and independently, a *new*,
unrelated optional parameter `fwd_module` was added. `_correlate_removed_parameter`'s pure name-similarity
scoring picks `fwd_module` as the correlation target instead of `param` — `fwd_module` contains `module` as
a literal substring, giving it a much higher `difflib.SequenceMatcher` score than the actually-correct
`param`, even though `param` is the parameter that structurally took over `module`'s old position and role.

**Why this wasn't "fixed" by changing the scoring algorithm under time pressure**: a position-based
tiebreaker was considered, but three existing, deliberately-designed unit tests
(`test_correlate_removed_parameter_finds_a_close_rename`,
`test_correlate_removed_parameter_ignores_preexisting_unrelated_params`,
`test_correlate_removed_parameter_returns_none_for_unrelated_names`) specifically assert that pure
positional coincidence must never override the name-similarity floor (see the last of those three: a
same-position-but-totally-unrelated name pair must return `None`, not a low-confidence guess). A correct fix
needs position to work as a *bounded* tiebreaker among otherwise-plausible candidates, not an override — that
needs its own careful design and test coverage, not a rushed change. Tracked as real follow-up work, not
silently left unmentioned.

See `tests/fixtures/transformers-pipeline-param-rename/` for a fixture demonstrating the full loop working
*correctly* end to end, using a different, unambiguous real rename.
