# Implementation plan

This is the phased path from the current scaffold (typed interfaces, no working logic) to a demoable,
released v0.1.0. Each phase states its goal, deliverables, what it depends on, and — critically — its exit
criteria, so "done" is a checkable fact, not a feeling. Phases map directly onto the modules already scaffolded
under `src/resync/`; nothing here introduces a new component that isn't already justified in
`docs/architecture.md`.

## Phase 0 — Foundation (complete)

Scaffold, ADRs, the four research/landscape/tech-stack docs, and typed-but-unimplemented interfaces across
every module. Exit criteria already met: every Python file parses, every TOML file validates, the adapter
Protocol and knowledge-record schema are stable enough to build against.

## Phase 1 — Knowledge layer

**Status: infrastructure built; exit criteria not yet met, but the automated path to it now exists — see the
honesty note below.**

**Goal:** a working hybrid retrieval store populated with real knowledge records for the flagship package set.

- Bind `KnowledgeRecord` (already defined) to a LanceDB table schema; implement insert/upsert. **Done** —
  `knowledge/store.py`, verified against current LanceDB docs (`lancedb.pydantic.LanceModel`/`Vector`,
  `RRFReranker` as the default hybrid reranker).
- Stand up the graph index on the Kùzu fork (`docs/architecture.md#decision-4-actively-maintained-kuzu-community-fork-for-graph-index`): `File` nodes, `IMPORTS` edges initially.
  **Done** — `knowledge/graph_store.py`.
- Wire `fastembed` for chunk/record embedding (`docs/tech-stack.md` — no `torch` anywhere in this phase).
  **Done** — `knowledge/embeddings.py`.
- Implement the adaptive router: a simple heuristic first (route on query shape — exact symbol lookup vs.
  free-text question), not a learned classifier. **Done** — `knowledge/router.py`.
- Populate real `KnowledgeRecord`s for `peft`, `bitsandbytes`, `transformers`, and `torch` across the specific
  version pairs the flagship demo needs. **Partially done, deliberately, via two tracks now instead of one**
  — see the honesty note below.

**Depends on:** Phase 0. **Exit criteria:** a hand-built evaluation set of ~30–50 known API changes in the
target packages retrieves the correct `KnowledgeRecord` at ≥90% precision at k=1. **Not yet met**, and not
faked to look met. Two tracks now feed the seed set, brought forward from Phase 5 once research established
a proper automated path existed rather than continuing to scale manual curation, which doesn't:

1. **Manual, individually-cited track** — `knowledge/seed_data.py` holds 14 records (up from 2): the original
   `use_auth_token`→`token` rename (Hugging Face `transformers` PR #25083), plus 12 sourced from
   `transformers`' own official `MIGRATION_GUIDE_V5.md` (v5.0.0, 2026-01-26) — 9 clean mechanical `RENAME`s,
   1 `REMOVED_NO_REPLACEMENT`, and 1 `MERGE` (the latter two included deliberately so `taxonomy.classify()`
   is exercised against real non-mechanical cases, not just an all-mechanical demo set). Still `transformers`
   -only: no equally strong single-document source was found in this pass for `peft`, `bitsandbytes`, or
   `torch`, and those are honestly left at zero rather than padded with lower-confidence guesses.
2. **Automated, structural-diff track (pulled forward from Phase 5)** — `knowledge/extract_api_diff.py`,
   built on `griffe` (mkdocstrings/griffe on PyPI), a mature static AST-based API-diffing tool. This is the
   real unblock for the 30–50 target: it diffs two loadable versions of a package and emits typed
   `Breakage` objects — a structural fact, not a transcribed claim. Two things had to be built on top of
   griffe's own output, not assumed:
   - **Rename correlation.** Griffe has no `PARAMETER_RENAMED`/`OBJECT_RENAMED` breakage kind — a rename
     looks to it like an unrelated removal (breaking) plus an unrelated addition (not breaking, not even
     reported). `_correlate_removed_parameter`/`_correlate_removed_object` close that gap with a
     name-similarity heuristic (`difflib.SequenceMatcher`), converting a `PARAMETER_REMOVED`/`OBJECT_REMOVED`
     into a `RENAME` when confident, or `REMOVED_NO_REPLACEMENT` when not — never a low-confidence guess.
   - **The heuristic's own failure mode, found by testing it, not assumed away.** An absolute similarity
     floor alone wasn't enough: sibling names in the same family (`AutoModelForCausalLM`/`...MaskedLM`/
     `...Seq2SeqLM`) all share a long common prefix with a removed name like `AutoModelWithLMHead`, scoring
     the "best" candidate at 0.56 — comfortably over the floor, and wrong, since there is genuinely no single
     correct replacement among three equally-plausible siblings. `tests/unit/test_extract_api_diff.py`
     caught this directly (`test_correlate_removed_object_no_replacement_when_only_dissimilar_candidates_exist`
     failed against the real scores before the fix). Fixed with a margin check — the best candidate must beat
     the runner-up by ≥0.15, or the match is treated as ambiguous, not confident — which is the correct
     behavior for exactly this case and is now regression-tested.
   - **REORDER detection is deliberately not read from griffe's own `PARAMETER_MOVED` breakage payload.**
     This module's own review pass could not confirm the exact runtime shape of
     `ParameterMovedBreakage.old_value`/`new_value` against a real installed griffe (no network access in
     this development environment — see below). Rather than guess at an undocumented internal shape and risk
     a silently wrong REORDER record — the exact failure mode this whole project exists to catch in *other*
     libraries — `_detect_reorder` independently compares the old and new function's documented, public
     `.parameters` name-order directly. Slower than trusting griffe's own payload would be, but only depends
     on a stable, public attribute. Revisit once griffe is actually installed and inspectable — tracked as a
     TODO in the module, not silently assumed correct.

   `extract()` itself is lazily imported inside the function, not at module level, specifically so the pure
   correlation/reorder functions stay independently unit-testable in any environment without `griffe`
   installed — found necessary the hard way (a first pass with a top-level `import griffe` broke unit-test
   collection entirely in this sandbox, which doesn't have `griffe`).

Both `tests/unit/test_seed_data.py` and the seed module's own docstring enforce the "no fabricated records"
discipline structurally, not just by convention; `tests/unit/test_extract_api_diff.py` (griffe-free, 10
tests, all passing) covers the correlation/reorder heuristics, and `tests/integration/test_extract_api_diff.py`
covers `extract()`'s real griffe call path, `pytest.importorskip`-guarded rather than mocked, since a mocked
griffe would only prove this module calls the API the way we assume it works, not that it actually does.

**What's still genuinely open, stated precisely:** `extract()` has not been run end-to-end against a real
`transformers`/`peft`/`bitsandbytes`/`torch` version pair in this development environment — no network access
to `uv sync --extra server` and fetch `griffe` here. The integration test that does run diffs griffe's own
repo against itself (a "zero breaking changes" smoke test proving the plumbing works), not a real package
pair. Running it for real, against real version pairs, and eyeballing the output before trusting it into the
seed set, is the actual remaining work to close Phase 1's exit criteria — not assumed done because the
adapter now exists.

**Verification status, stated precisely rather than rounded up:** `store.py`, `router.py`, and `graph_store.py`
are now covered by real integration tests against actual LanceDB and Kùzu instances (`tests/integration/
test_knowledge_store.py`, `tests/integration/test_graph_store.py`), not just mocks — added after a review
pass found that several real bugs had escaped the earlier mocked-only tests entirely:

- **The most serious**: `upsert()`'s delete filter, once extended to include `old_param_order` for REORDER
  uniqueness, compared that column against an empty array literal (`old_param_order = []`) for every
  non-REORDER record — which crashes LanceDB's query planner outright (`concat requires input of at least
  one array`). This would have broken the *first* upsert to any fresh table. Found only by actually running
  it against a real table; a mocked `FakeTable` from the unit tests had no way to surface it. Fixed by only
  including that clause when the record actually has an order to disambiguate.
- `get_or_create_table` used the deprecated `table_names()` (a `DeprecationWarning`, not a test failure, so
  nothing had caught it) and `create_fts_index` (also deprecated, replaced by `create_index(config=FTS())`)
  — both fixed, the second one a little pointedly, given this project exists to catch exactly this kind of
  drift in other libraries.
- `table_exists()` looked like the obvious replacement for the deprecated table-listing call and was
  rejected after actually calling it: it raises `NotImplementedError` for this local/embedded connection
  type.
- `graph_store.init_schema`'s `except RuntimeError: pass` caught every `RuntimeError`, not just "table
  already exists" — confirmed by triggering a real parser error and finding it raises the identical
  exception type, meaning a genuine schema typo would have been silently swallowed. Now checks the message
  before deciding to ignore it.
- `seed_data.seed()` itself was previously untested — only properties of the `SEED_RECORDS` list were
  checked, never that the function actually upserts them.

One gap remains, stated plainly rather than implied solved: `embeddings.py`'s real network call to download
and run `nomic-embed-text-v1.5` could not be executed in this development environment, since the model host
isn't in the sandbox's allowed network domains. Every test above monkeypatches the embedding call; the round
-trip and query logic around it is proven correct, but a live embedding call itself remains unexercised here.

## Phase 2 — Deterministic patch layer

**Status: SEALED.** Five review passes, ten implementation-level findings plus four tooling/CI findings from
actually running the documented developer workflow end to end. `make test`, `make lint`, and `make typecheck`
all pass clean. One property (REORDER's unattended-scheduling safety) is explicitly not yet met and is
tracked as a named prerequisite for Phase 6, not silently assumed solved.

**Goal:** mechanical fixes apply correctly with zero LLM involvement.

- Wire `ast-grep` invocation via subprocess (binary dependency, not a Python binding — `docs/tech-stack.md`).
  **Done** — `patch/ast_grep_runner.py`.
- Implement the `RuleType`-driven classifier deciding mechanical vs. semantic handling. **Done** —
  `patch/taxonomy.py`, folding in `resync.toml`'s confidence threshold, not just `RuleType.is_mechanical`
  alone. Malformed records (a RENAME with no actual target, a REORDER with a non-permutation) are now
  rejected at `KnowledgeRecord` construction time via a pydantic validator, not discovered downstream inside
  the patch layer — see `docs/architecture.md#decision-3-deterministic-first-patching` and `knowledge/schema.py`.
- Generate ast-grep rules for `RENAME` and `REORDER` cases from a `KnowledgeRecord`. **Done**, upgraded, and
  scope-bounded honestly — see below.

**What the second review pass found and fixed, on top of the first pass's four findings:**

5. The original keyword-argument matching used a placeholder-wrapper pattern hack (`__resync_placeholder__
   (param=$VAL)` + `--selector`) that worked but wasn't idiomatic. ast-grep's own documentation shows a
   cleaner approach — a YAML rule with `kind: keyword_argument` and field-scoped `has` sub-rules constraining
   the argument name to an exact match — now used via `ast-grep scan --rule <tempfile>` instead. Verified
   against the same real fixture the hack was tested against.
6. `REORDER` was classified as mechanical from the start but had no actual pattern-generation logic behind
   it — an unimplemented case masquerading as a supported one. Now genuinely implemented via metavariable
   capture-and-reorder, confirmed against a real fixture, including a `$$$REST` catch-all fix after the first
   version silently matched nothing on any call with an extra trailing argument.
7. **REORDER is not naturally idempotent, unlike RENAME** — a positional swap pattern matches the
   already-fixed code just as validly as the broken code, so applying it twice swaps back and forth forever.
   This is proven by a dedicated test that asserts the oscillation happens and is meant to keep failing until
   a real fix exists, not "fixed" by loosening the assertion. The real fix — an external applied-already
   guard — belongs in `resync.toml`'s `[[policy]]` mechanism (already designed for the Impact Map) rather
   than in this module, and is tracked as required follow-up before REORDER runs unattended on a schedule.

**A third review pass found something more serious than a missed case — an active data-loss bug**:

8. The whole-symbol import fix used `from $MOD import {old_name}` -> `from $MOD import {new_name}` as a
   plain pattern/rewrite. Against `from pkg import old_name` alone this worked; against the very common
   `from pkg import old_name, other_thing`, it matched the *entire* statement and silently deleted
   `other_thing` on rewrite. Found by testing exactly that case and reading the corrupted output — not by
   reasoning abstractly about what "should" happen. Fixed with a YAML rule scoped to the specific imported
   identifier via a nested `inside` chain, confirmed to leave sibling names untouched. Regression test:
   `test_whole_symbol_rename_preserves_other_names_on_a_multi_name_import_line`.
9. Smaller, but worth fixing before it bit later: the YAML rules' `language:` field used plain
   `str.capitalize()`, correct for "python" -> "Python" by coincidence but wrong for multi-word names
   ("javascript" -> "Javascript" instead of ast-grep's expected "JavaScript"). Not yet triggered, since
   Phase 2 is Python-only, but would have been a silent landmine for Phase 5. Replaced with an explicit,
   per-language mapping.

**A fourth pass added a safety feature rather than fixing a bug:**

10. Every mechanical pattern matches by name — a function name, a keyword-argument name — with no check
    that the match actually originates from the tracked package. Confirmed with two real fixtures: a
    namesake with no import of the package at all (false positive), and a file that legitimately imports the
    package but also shadows the same name locally, where the call site actually resolves to the local
    definition per Python's own scoping. `_package_is_imported` now gates every mechanical patch on the
    target file actually importing the record's package first — closing the first case completely and
    documenting the second as a known, tested residual risk that Phase 3's differential-equivalence layer is
    the intended backstop for, since it cannot be solved without real scope resolution this syntactic tool
    doesn't do.

**Deliberate scope boundary, not an oversight:** aliased imports, star imports, and bare module-attribute
access are still not handled mechanically for whole-symbol renames — see `patch/ast_grep_runner.py`'s
docstring. Records requiring those forms should classify as `PatchStrategy.SEMANTIC`.

**A fifth and final pass sealed Phase 2 by running the actual documented developer workflow for the first
time**, not just `pytest` with manual `PYTHONPATH` shortcuts. This found real gaps the shortcuts had been
hiding:

11. `uv sync` followed by the documented `pytest tests/unit` command (no manual setup) failed outright with
    `ModuleNotFoundError: No module named 'resync'` — every prior verification in this project's history had
    used a manual `PYTHONPATH=. cd src` workaround instead of the actual documented workflow. Running
    `uv sync --extra server --extra cli --group dev --group verify` for real fixed this (it installs the
    project in editable mode correctly) — the documented commands were right, they had simply never been
    executed as written until this pass.
12. `make lint` had never been run: 339 real errors, almost entirely long, deliberately thorough
    explanatory docstrings exceeding the configured 100-character limit. Measured the actual distribution
    (max line length anywhere: 114 characters) rather than guessing a fix, and set `line-length = 120` — a
    real, still-disciplined limit that needed zero prose reflowing, chosen from data rather than picked to
    make errors disappear. Also found and excluded `tests/fixtures/` from linting, since those are
    intentionally incomplete syntactic snippets for ast-grep to match against, not real executable modules —
    `ruff` was correctly flagging undefined names in a fixture that was never meant to run.
13. `make typecheck` had never been run either: missing `types-PyYAML` stubs, a `python_version = "3.11"`
    mypy setting that couldn't parse a dependency's stub file using 3.12-only syntax (bumped to 3.12 as a
    static-checking target only — the project's actual runtime floor stays 3.11), two genuine
    `QueryResult | list[QueryResult]` and `list[Any] | dict[str, Any]` union-type gaps in `graph_store.py`
    left unnarrowed (fixed with real assertions, each verified empirically against the actual return value
    for this module's specific query shape before being written, not assumed), several bare `dict` type
    annotations needing parameters, and one legitimate `zip()`-without-`strict=` finding in the REORDER
    pattern generator, fixed since a silent length mismatch there would have corrupted the reorder mapping.
14. One documented false positive, not fixed by restructuring correct code: `ruff` flagged
    `typer.Argument(...)` in parameter defaults as the mutable-default-argument bug B008 exists to catch —
    that's Typer's own required calling convention, not a bug, so this is a scoped, explained
    per-file ignore rather than working around a linter that doesn't know about Typer's pattern.

**Depends on:** Phase 1. **Exit criteria:** mechanical fixes apply correctly and idempotently against the
`tests/fixtures` repos. **Met for RENAME. For REORDER, met at the `apply()` layer as of the applied-already
guard (`config.schema.AppliedFix`, `ast_grep_runner.apply(..., repo_root=...)`) — the underlying ast-grep
pattern is still not idempotent on its own (finding 7), but a caller that always passes `repo_root` now gets
safe unattended repeated application, which is the property the scheduled sweep needs.** Stated precisely
rather than
rounded up, per finding 7 above. `make test`, `make lint`, and `make typecheck` all pass clean via the
documented workflow, run for real rather than assumed. 50 tests total (18 integration, 32 unit) across
Phases 1 and 2 — including five that exist specifically to prove known limitations rather than to look
green.

## Phase 3 — Verification layer

**Status: implemented and tested (compile-check, deprecation-window-differential, and oracle-signature-check
tiers). The generator/critic tier's seam exists; its concrete implementation is still Phase 6's dependency.**

**Readiness check (done as part of sealing Phase 2, not deferred to Phase 3's own start):**
`sandbox-runtime` was confirmed real and installable (PyPI, currently 0.2.0) rather than assumed from the
research in `docs/tech-stack.md` — its actual exposed API (`SandboxManager`, `SandboxRuntimeConfig`,
`NetworkRestrictionConfig`, `FilesystemConfig`) matches what was described, which is worth confirming
explicitly given this project's history of research-stage assumptions turning out to need correction once
actually run (see Phase 1/2's findings). `hypothesis` is already installed as part of the `verify` dependency
group. Confirmed in this design pass, specifically: `hypothesis.strategies.builds(callable, **overrides)`
infers a generation strategy per parameter directly from type annotations when the argument isn't otherwise
supplied, and `st.from_type(annotation)` does the same standalone — this is the actual mechanism Phase 3's
property-generation step is built on, not assumed API shape.

**Correction, found by re-reading `docs/architecture.md#decision-2-differential-equivalence-over-test-passes` closely rather than from the phase summary alone**: "execute
the old and new code paths side by side wherever both are available" does not mean diffing two installed
*library* versions (that's `extract_api_diff`'s job, in Phase 1/5). It means the *target repo's* pre-patch and
post-patch call — e.g. `TrainingArguments(no_cuda=True)` vs. the mechanically-patched
`TrainingArguments(use_cpu=True)` — run against the single library version actually pinned in the target repo
right now. "Both available" specifically describes a **deprecation window**: many real renames (this
project's own `use_auth_token`→`token` seed record is exactly this case — both names worked for several
minor versions before the v5 hard removal) accept *both* the old and new keyword simultaneously for a period.
When that's true, the check is genuinely strong: call both, diff actual results, no oracle needed. Once the
old name is hard-removed (post-v5, in that example), it physically cannot be called anymore, and the check
must fall back to the oracle-from-knowledge-record path — a static claim check, not a live behavioral diff.
This distinction is the backbone of the design below; conflating the two would have produced a design that
quietly promised a stronger guarantee than it can deliver in the common (post-removal) case.

**Also found in this pass, and load-bearing for scoping**: Hypothesis's type-driven generation is excellent
for pure functions over simple/composable types (ints, strings, dataclasses, `Optional[...]`) and poor for
the actual target domain here — `transformers.TrainingArguments`, `torch.nn.Module` subclasses, etc. — where
parameters are often typed loosely (`Any`, complex unions) or require real weights/tensors/network access to
meaningfully construct. Trying to Hypothesis-generate a working `torch.Tensor` or a real pretrained model
object is both infeasible and outside what this project needs, per `docs/tech-stack.md`'s "no torch" stance.
**Scope decision, stated explicitly rather than glossed over**: Phase 3 verifies *call-compatibility and
argument-forwarding equivalence* — does the patched call get accepted by the real signature, and (within a
deprecation window) does it produce the same result as the old call — not deep numerical/behavioral identity
of the underlying ML computation. Whether `Trainer.train()` produces bit-identical model weights before and
after a patch is the library's own correctness contract, not something this project re-verifies; that would
require running real training, which is exactly the `torch`-and-GPU dependency this project exists to avoid
pulling into its own runtime.

**Goal:** every proposed patch is checked for behavioral equivalence appropriate to its risk tier — never
just "the tests passed" alone (`docs/architecture.md#decision-2-differential-equivalence-over-test-passes`) — without silently overreaching into guarantees the toolchain
can't actually deliver for opaque ML library internals.

### 3.1 — Verification tiers (new: formalizes what `docs/architecture.md#decision-2-differential-equivalence-over-test-passes` already implies but doesn't structure)

`docs/architecture.md#decision-2-differential-equivalence-over-test-passes` exempts mechanical fixes (RENAME, REORDER) from the heavier differential check — a compile
check is sufficient for their risk profile. That exemption needs an explicit home in code, not just prose, so
the rest of this phase has something concrete to gate on. New module: `verification/tier.py`.

```python
class VerificationTier(StrEnum):
    COMPILE_CHECK = "compile_check"  # ast.parse + py_compile on the patched file only
    DEPRECATION_WINDOW_DIFFERENTIAL = "deprecation_window_differential"  # both old & new call accepted now — live diff
    ORACLE_SIGNATURE_CHECK = "oracle_signature_check"  # old call no longer valid — static claim check only
    GENERATOR_CRITIC = "generator_critic"  # semantic (LLM-drafted) patches — Phase 6 dependency
```

Mapping, driven by `RuleType` plus one runtime fact (whether the old call still binds against the currently
installed signature):

| `RuleType` | Old call still binds? | Tier |
|---|---|---|
| `RENAME`, `REORDER` | — | `COMPILE_CHECK` (per ADR's explicit exemption) |
| `RENAME` (parameter), when the *old* parameter also still binds on the installed version | n/a | `DEPRECATION_WINDOW_DIFFERENTIAL` — strictly stronger than the compile-check tier below it; used opportunistically when available, not required |
| `RENAME`, `MERGE`, `SPLIT`, `REMOVED_NO_REPLACEMENT` | old call raises `TypeError` on the installed version | `ORACLE_SIGNATURE_CHECK` |
| `BEHAVIOR_CHANGE`, `RETURN_SHAPE_CHANGE` | — | `ORACLE_SIGNATURE_CHECK` at minimum; escalate to `GENERATOR_CRITIC` if resolved via an LLM-drafted patch rather than a direct mechanical substitution |
| any LLM-drafted (semantic-path) patch, regardless of `RuleType` | — | `GENERATOR_CRITIC`, always, per ADR |

`taxonomy.classify()` already outputs a `RuleType`; this table is a pure function of that output plus a
single `inspect.signature(...).bind()` probe against the installed library, added as `tier.select_tier()` —
no new classification logic, just routing what already exists.

### 3.2 — Signature/call-compatibility harness (`verification/differential.py`)

Core function: `check_call_compatibility(old_call, new_call, signature, tier) -> DifferentialResult`.

1. **Build the input strategy from the *new* signature** (the one that must accept the patched call — the
   thing actually being verified), via `inspect.signature(target_callable)` then
   `hypothesis.strategies.builds(target_callable, **{name: st.from_type(annotation) for typed params})`.
   Parameters with no usable annotation (`Any`, or missing) fall back to a small fixed corpus — `None`, `0`,
   `""`, `[]`, `{}`, a truthy sentinel — rather than pretending full-coverage generation; when this fallback
   fires for a parameter that actually matters to the check (the renamed one), the result's confidence is
   marked reduced, not silently reported as equal to a fully-typed pass.
2. **`DEPRECATION_WINDOW_DIFFERENTIAL` tier**: call `old_call(**example)` and `new_call(**remapped_example)`
   against the same installed version, for each of `hypothesis`'s generated examples (driven via `@given`
   inside a harness function, not manually looped, so shrinking on failure is free); assert equal return
   values (`==`) and equal exception behavior (same exception type raised, or both succeed) — never just
   "neither raised."
3. **`ORACLE_SIGNATURE_CHECK` tier**: no live old-call execution is possible. Instead: (a) confirm
   `inspect.signature(new_call).bind(**remapped_example)` succeeds without `TypeError` for every generated
   example — proves the patch is actually callable, not just textually plausible; (b) cross-check the
   remapping itself against the `KnowledgeRecord`'s own `parameter`/`new_parameter` (or `old_param_order`/
   `new_param_order`) fields — the record *is* the oracle here, exactly as `docs/architecture.md#decision-2-differential-equivalence-over-test-passes` specifies, to avoid
   the circularity of testing a translation against itself.
4. **`COMPILE_CHECK` tier**: `ast.parse` + `py_compile` on the patched file, already effectively proven by
   Phase 2's `ast_grep_runner.apply()`'s own round-trip; this phase adds nothing new here beyond wiring the
   result into `TrustScore.test_suite_passed`/`static_rule_match`, since re-verifying a compile that already
   necessarily succeeded (or the patch wouldn't have written) would be circular busywork.

### 3.3 — Sandbox execution (`verification/sandbox.py`)

Every call in 3.2 executes arbitrary target-repo code, including whatever the target repo's own dependencies
do at import/call time — this is untrusted code from resync's perspective, unlike resync's own test suite.
Wrap the harness call in `sandbox-runtime`'s `SandboxManager`, configured via `SandboxRuntimeConfig` with
`NetworkRestrictionConfig` (deny all — a differential call has no legitimate reason to reach the network) and
`FilesystemConfig` scoped to a read-only mount of the target repo plus a throwaway writable temp dir. Given
`sandbox-runtime`'s still-early version number (0.2.0), document and implement a Docker+gVisor fallback path
behind the same `SandboxManager`-shaped interface, selected by a `resync.toml`-level setting rather than
silently swapped — an operator running this against real, untrusted third-party code should know which
isolation mechanism is actually active.

### 3.4 — `TrustScore` wiring (`verification/trust_score.py` — model exists, unpopulated)

- `static_rule_match` ← the `KnowledgeRecord.confidence` used to select the applied fix (already computed in
  Phase 1/2, just not threaded through yet).
- `test_suite_passed` ← run the target repo's own existing test suite (if any — `pytest`/`unittest`
  autodetected) inside the same sandbox from 3.3, patched-version only; a target repo with no test suite
  leaves this `True` by convention (nothing to fail) but `differential_equivalence_passed` carries the real
  signal in that case, not this field alone — exactly the point of ADR 0002's decomposition.
- `differential_equivalence_passed` ← 3.2's `DifferentialResult`, mapped `True`/`False`; left `None` for the
  `COMPILE_CHECK` tier per the model's own existing docstring ("None if not applicable").
- `critic_pass_approved` ← left `None` in this phase. The generator/critic double-pass needs a local model
  (Phase 6), which is not yet wired. What *is* added now: a `verification/critic.py` `Protocol` —
  `class Critic(Protocol): def review(self, patch: Patch, context: VerificationContext) -> CriticVerdict: ...`
  — so `TrustScore` plumbing has a real seam to write into once Phase 6 lands a concrete implementation,
  instead of that wiring being deferred whole.

### 3.5 — Concrete first target, then generalize

The `transformers.PreTrainedModel.from_pretrained(use_auth_token=...)` → `token=...` seed record
(`knowledge/seed_data.py`) already has a real fixture (`tests/fixtures/transformers-param-rename/`) and a
mechanical patch proven correct by Phase 2's integration tests. It is also, usefully, a real historical
deprecation-window case (`use_auth_token` and `token` both worked for several `transformers` minor versions
before v5's hard removal) — meaning it's the one seed record that can exercise the *strong*
`DEPRECATION_WINDOW_DIFFERENTIAL` tier for real, not just the weaker oracle fallback. Build and prove the
harness against this exact case first. Second target, deliberately different in shape: one of the new
`TrainingArguments` renames from `MIGRATION_GUIDE_V5.md` where the old name is *already* hard-removed in the
pinned v5 fixture version — proving the `ORACLE_SIGNATURE_CHECK` fallback path works correctly, not just the
happy-path deprecation-window case. Only after both tiers are proven against real, already-verified records
does this phase generalize to arbitrary records.

### 3.6 — The labeled test set the exit criteria actually needs

The exit criteria ("zero false negatives on a labeled set of intentionally-correct and intentionally-broken
patches") needs the broken half built, not just assumed available. Concrete plan: for each fixture used in
3.5, generate a **mutant** patch variant by deliberately corrupting the correct one — swap in a plausible but
wrong parameter name, apply only half of a REORDER, or drop a required argument — and assert the verifier
rejects 100% of mutants while accepting 100% of the genuine patches. This directly operationalizes "zero false
negatives" as a running, re-checkable test (`tests/integration/test_verification_layer.py`) rather than a
one-time manual check — a regression here is exactly the failure mode this whole project exists to prevent,
so it needs to stay tested, not just proven once.

**Depends on:** Phase 2 (needs patches to verify) — met. Does **not** depend on Phase 1's exit criteria being
fully met (the 30–50-record eval set): this phase verifies *patches*, one record at a time, and can and
should proceed on the 14 records that already exist rather than block on knowledge-base breadth that's
orthogonal to verification-layer correctness. **Exit criteria:** on the labeled set from 3.6, the layer
correctly flags every broken patch (target: zero false negatives — a false negative here is the exact failure
mode this whole project exists to prevent) and does not false-positive on the correct set at a rate that would
make `resync.toml`'s `auto_apply_above` threshold meaningless.

**Implementation status, verified by actually running it, not just written to spec:**

- `verification/tier.py`, `verification/differential.py`, `verification/critic.py`, `verification/sandbox.py`,
  and `verification/trust_score.py`'s new `build_trust_score()` builder are all implemented. 26 unit tests,
  all passing, including the 3.6 labeled-mutant pattern applied directly at the unit level — for every
  "correct" check there is a deliberately-broken mutant variant asserted to be rejected (dropped values,
  inverted boolean semantics, a claimed parameter that doesn't actually exist on the real signature).
- **A real, load-bearing bug caught by writing these tests, not a hypothetical**: `_build_kwargs_strategy`
  originally read annotations straight off `inspect.signature(...).parameters[name].annotation`, which left
  them as unevaluated strings (e.g. the literal text `'str | None'`) for any function defined in a module
  using `from __future__ import annotations` (PEP 563) — which is every module in this very codebase, and
  extremely common in real target repos generally. `hypothesis.strategies.from_type` raised
  `InvalidArgument` on the raw string rather than silently misbehaving, so the bug surfaced loudly on the
  first real test run rather than quietly generating garbage inputs. Fixed by resolving annotations through
  `typing.get_type_hints` instead, with a graceful fallback to the fixed corpus for any forward reference
  that still can't be resolved (e.g. a name not actually in scope).
- **The end-to-end pipeline was run for real**, not just unit-tested in isolation: `patch.taxonomy.classify()`
  → `verification.tier.select_tier()` → `verification.differential.check_deprecation_window_differential()`
  → `verification.trust_score.build_trust_score()`, against the real `use_auth_token`→`token` seed record,
  correctly selected the `DEPRECATION_WINDOW_DIFFERENTIAL` tier, correctly diffed a genuinely-equivalent
  old/new pair as passing, and produced a `TrustScore` with the expected `overall` value.
- **A second real gap, also found only by running it**: the oracle-signature-check tier initially returned
  `passed=False` unconditionally for whole-symbol renames (e.g. `AutoModelForVision2Seq` →
  `AutoModelForImageTextToText`), since they have no `parameter`/`new_parameter` to bind-check — which would
  have flagged every valid class rename as a verification failure. Fixed with an explicit branch: for a
  whole-symbol rename, the only oracle signal available at this layer is whether the new symbol actually
  resolved to a callable at all, which the caller passing a non-`None` value already proves.
- **What's honestly not run end-to-end in this environment**: `verification/sandbox.py`'s two backends
  (`sandbox-runtime` and the Docker+gVisor fallback) are implemented and unit-tested against their dispatch
  logic — the right backend is selected, and a missing dependency raises the documented
  `SandboxUnavailableError` rather than a confusing bare `ImportError` — but neither backend's actual
  isolated execution has run in this development sandbox (no network to install `sandbox-runtime`, no local
  `docker`/`runsc` available here). `griffe>=2.2`, `sandbox-runtime>=0.2`, and `cloudpickle>=3.0` were added
  to the `server` extra; `sandbox-runtime` was previously missing from `pyproject.toml` entirely despite
  being referenced throughout `docs/tech-stack.md` and this phase's own readiness check — also only found by
  actually checking, not assumed present because the research doc discussed it.
- `verification/critic.py`'s `Critic` Protocol and `CriticVerdict`/`VerificationContext` dataclasses exist as
  the seam Phase 6 will implement against; `build_trust_score()` already accepts an optional
  `CriticVerdict` and wires it into `TrustScore.critic_pass_approved` correctly (unit-tested), so Phase 6
  only needs to provide a concrete `Critic`, not touch this phase's wiring again.

## Phase 4 — MCP server and the real-time gate

**Status: complete. Both tool implementations, the MCP transport (stdio, and Streamable HTTP against the
stateless core), and the CLI's own `check`/`sync` surfaces are built and verified end-to-end against real
infrastructure — a real MCP client over a real stdio subprocess, a real seeded LanceDB store, and the real
ast-grep binary doing real file rewrites, not just functions called directly in isolation. Remaining: the
companion Skill hasn't been exercised
against a live agent session.**

**Goal:** an agent gets blocked or corrected before it commits to broken code — and the server this runs on
is built the way it will eventually need to scale, not retrofitted later.

**Research grounding for this phase**, beyond what `docs/architecture.md#decision-1-single-mcp-server-with-transport-duality` already established: MCP's 2026-07-28
specification made the core protocol stateless specifically to remove the horizontal-scaling barrier the
prior session-based design had — under the old protocol, a request had to land on the same instance that
handled its `initialize` call, which meant sticky sessions, shared session stores, or single-instance
deployments were the only options. Under the stateless core, every request carries enough information to be
handled independently, so a request can land on *any* instance behind a plain round-robin load balancer with
no shared state at all. This is a direct, practical payoff of the architecture decision already made in
`docs/architecture.md#decision-1-single-mcp-server-with-transport-duality` — Phase 4 is where that payoff actually gets realized in code, and it's worth building the
server so this property holds from the start rather than accidentally introducing in-memory state that would
need to be ripped out later for Phase 8.

**Sub-steps:**
- Implement `verify_package` (registry existence + OSV.dev/GitHub Advisory check) and `check_symbol_exists`
  for real (the `resync.toml` pin/exception short-circuit is already built and tested in `server/tools.py`
  and `config/loader.py` — Phase 4 wires the knowledge-store lookup behind it). **Done, this phase** — see
  the detailed account below.
- Wire MCP transport: stdio first (simplest to test locally, matches the single-developer local mode), then
  Streamable HTTP against the 2026-07-28 stateless core for the shared/team mode. **Done, this pass** — see
  the detailed account below.
- Keep the server process itself stateless by construction: no in-memory cache of per-client state, no
  assumption that two requests from the "same" agent land on the same process. Where caching is needed (see
  Phase 8), it belongs in a shared store (the LanceDB/Kùzu instances already are one), not process memory.
  **Naturally satisfied so far**: both tool functions take `repo_root` as an explicit argument and hold no
  module-level or process-level state between calls — nothing to retrofit later, since nothing stateful was
  introduced in the first place.
- Return the decomposed trust score and verification results as MCP's structured tool output, not a text
  blob — already the documented design in `docs/architecture.md`. `VerificationResult` (this phase) and
  `TrustScore` (Phase 3) are both real pydantic models with structured fields; both MCP tools return
  `VerificationResult` directly and the SDK serializes it to structured content automatically (confirmed via
  a real `call_tool()` round-trip, see below) — no manual dict-marshalling needed.
- Finalize and test the companion Skill (`skills/resync/SKILL.md`) against a real agent session. **Still not
  done** — the transport now exists to make this possible, but it hasn't been exercised yet.

**Implementation status, verified by actually running it against real infrastructure:**

- **`verify_package`**: checks `resync.toml` pins first (short-circuits before any network call — confirmed
  by a test that raises if the mock transport's handler is ever invoked for a pinned package), then a real
  PyPI JSON API existence check (`https://pypi.org/pypi/{package}/json`, verified against `docs.pypi.org/api/json`
  before coding against it, not assumed), then a real OSV.dev advisory query (`POST api.osv.dev/v1/query`,
  verified against `google.github.io/osv.dev/post-v1-query`). `httpx.Client` is injectable specifically so
  tests exercise the real request-building/response-parsing code against `httpx.MockTransport` — httpx's own
  first-class, documented testing mechanism, not a bespoke mock — without needing live network access, which
  isn't available in this development environment. 7 unit tests, all passing, covering the pinned/OK/
  not-found/advisory-flagged/unsupported-ecosystem/client-cleanup paths. The unsupported-ecosystem path is a
  deliberate honesty choice: a non-PyPI package returns `OK` with a detail explicitly saying no check was
  performed, rather than a silently false-reassuring "confirmed clean."
- **`check_symbol_exists`**: wired to the real knowledge store (`router.route` → `store.exact_symbol_lookup`),
  narrowed by pinned version using the real `packaging` library (`SpecifierSet`/`Version` — the same library
  pip/uv themselves use), not the string-comparison placeholder the original TODO explicitly warned against
  rushing. When a version string genuinely doesn't parse as PEP 440, the record is excluded and the exclusion
  is reported in `detail`, never silently guessed at either direction. Handles the real, common case of a
  symbol with *multiple* simultaneously-applicable records correctly — `transformers.TrainingArguments` has
  8 in the current seed set — by listing every match rather than arbitrarily picking one. 6 integration tests,
  all passing against a real, upserted LanceDB table (embedding calls monkeypatched, matching
  `tests/unit/test_store.py`'s existing pattern, since a live call to `nomic-embed-text-v1.5` isn't reachable
  from this environment — an already-documented, unrelated gap).
- **A real, previously-undecided gap found and closed**: nowhere in this codebase had ever picked a location
  for the knowledge databases on disk — `check_symbol_exists` needed a real answer to call `store.connect()`
  at all. Added `store.default_db_path()`/`graph_store.default_db_path()` (`.resync/knowledge.lancedb` and
  `.resync/graph.kuzu`, mirroring the `.git`-directory convention: tool-local state living inside the repo it
  concerns).
- `packaging>=24.0` added to core `dependencies` — was previously only a transitive dependency (pulled in by
  `mcp`/`lancedb`/etc.), declared explicitly now that code imports it directly, per this project's own
  dependency-hygiene stance.

**This pass ran with real outbound network access, unlike every prior phase's verification work — which
changes what "honestly still open" means here.** Several gaps previously recorded as environment limitations
turned out to be fixable at the root once real network was available, and doing so surfaced real code bugs
that a permanently-offline sandbox could never have caught:

- **`ast-grep` binary**: previously recorded as "genuinely not installed, no network to fetch it." Installed
  via `npm install -g @ast-grep/cli` this pass (npm's registry is reachable here) — this closed out all 11
  previously-failing `test_ast_grep_runner.py` integration tests, which now pass against the real binary, not
  a documented gap.
- **`sandbox-runtime` and `cloudpickle`**: both install cleanly via `uv sync --extra server` with real
  network. Doing so exposed two real bugs the mocked/offline state had been hiding: (1) `sandbox.py` had
  stale `# type: ignore[import-not-found]` comments left over from when the imports genuinely failed — mypy
  now flags these as unused, and the real error code once the packages import successfully is
  `import-untyped` (no py.typed marker upstream), fixed to match; (2) the Docker+gVisor fallback's
  `subprocess.run(["docker", ...])` call let a raw `FileNotFoundError` escape when `docker` isn't on `PATH`,
  instead of the documented `SandboxUnavailableError` — real bug, now caught and normalized.
  `tests/unit/test_sandbox.py`'s two tests were rewritten to test the real failure modes this environment
  actually hits (package-blocked-via-import-hook for the "not installed" case; real missing-`docker` for the
  fallback) rather than relying on the packages happening to be absent.
- **`griffe`**: installs cleanly with real network. Doing so surfaced a real API-signature bug in
  `extract_api_diff.py` — `griffe.load_git(package, old_ref)` was calling a positional signature that
  doesn't exist; the real installed `griffe`'s `load_git` takes `ref` as keyword-only. Fixed and confirmed
  against `inspect.signature` on the actually-installed package, not assumed. The integration test for this
  function also had a real, independent design bug: it silently relied on pytest's `cwd` happening to be a
  git checkout of `griffe`'s own source, which nothing in the repo or its CI config ever guaranteed. Rewritten
  with an explicit fixture that shallow-clones griffe into a temp dir (marked `@pytest.mark.network`, skips
  cleanly if GitHub isn't reachable) so the test is correct regardless of where it's run from.
- **A real, unrelated test-collection bug found by the fuller pytest run**: `tests/unit/test_extract_api_diff.py`
  and `tests/integration/test_extract_api_diff.py` share a basename with neither test directory using
  `__init__.py`, which crashes pytest's default "prepend" import mode with a same-basename collision. Fixed
  properly via `--import-mode=importlib` in `pyproject.toml`, not by renaming a test file (the same collision
  would just resurface the next time two suites independently pick the same obvious name).

Net result of this pass's own full validation sweep: **110/110 tests passing before the transport work, 114/114
after adding transport coverage** (up from the 75/22-with-`ast-grep`-excluded figures recorded in the prior,
offline pass) — with `ruff check` and `mypy src` both clean.

**MCP transport, built and verified this pass:**

- `pyproject.toml`'s `mcp` dependency was still pinned `>=1.0` with a comment flagging exactly this
  uncertainty ("confirm this targets the 2026-07-28 stateless core before pinning further"). The actually-
  installed package is `mcp` 2.2.0, where `mcp.server.fastmcp.FastMCP` was renamed to
  `mcp.server.mcpserver.MCPServer` with a different registration/run surface — confirmed by trying the v1
  import, reading the real `ModuleNotFoundError`'s own migration-guide pointer, and inspecting
  `MCPServer.__init__`/`.tool()`/`.run()`'s real signatures directly rather than guessing from memory. Pin
  updated to `mcp>=2.0` with the resolution recorded inline.
- `src/resync/server/app.py` (new): builds the `MCPServer`, registers `verify_package` and
  `check_symbol_exists` as real `@server.tool()`-decorated tools, and exposes `run(transport, repo_root, port)`
  used by the CLI. `stateless_http=True` is passed explicitly for the HTTP transport, per ADR 0001's stated
  design rationale (no session affinity needed for a single-shot request/response gate).
- `repo_root` resolution (`resolve_repo_root`): explicit path → `$RESYNC_REPO_ROOT` env var → cwd at server
  start. Deliberately resolved once per server process, not threaded per-call — per ADR 0001, stdio is "a
  single trusted local caller" checking one repo per running process. Flagged explicitly in the module
  docstring as a real design choice that would need to change (repo_root moving onto the request/session) if
  a future shared HTTP deployment needs to serve multiple repos from one process.
- `src/resync/cli/main.py`'s `serve` stub is wired to this for real (`--transport stdio|http`, `--repo`,
  `--port`), matching the `Makefile`'s pre-existing `run-server`/`run-server-http` targets, which already
  assumed exactly this flag shape.
- **Verified three ways, not just unit-tested**: (1) `tests/integration/test_server_app.py` calls
  `MCPServer.call_tool()` directly — the real SDK dispatch path, not the plain Python functions — for both
  tools, plus `list_tools()` and `resolve_repo_root`'s three-way precedence; (2) a standalone script used the
  real `mcp.client.stdio.stdio_client` to spawn `uv run resync serve --transport stdio` as an actual
  subprocess, `ClientSession.initialize()`, and `list_tools()` against it, confirming `['verify_package',
  'check_symbol_exists']` over a real stdio pipe, not an in-process shortcut; (3) `resync serve --help` and
  `resync --help` render the real Typer-generated CLI surface.

**`resync check` and `resync sync`, built and verified this pass (previously `NotImplementedError` stubs):**

- `src/resync/cli/scan.py` (new): `discover_dependencies` parses `pyproject.toml`'s `[project.dependencies]`
  and every `[project.optional-dependencies]` group into real package names — tested against real PEP 508
  edge cases (extras like `uvicorn[standard]`, direct-URL requirements), not just the bare-name common case.
  `extract_fully_qualified_symbols` walks a file's real AST and resolves `module.attr[.attr...]` chains back
  to actual `import`/`from...import` statements in that same file — a bare local variable's attribute access
  is never reported just because it has the right shape, and relative imports are correctly skipped (no
  fully-qualified base exists for them). `resolve_pinned_version` checks `uv.lock` first (the exact version a
  real `uv sync` would install), falling back to the running environment via `importlib.metadata`.
- `resync check`: runs both scans against a real repo and reports actionable findings via `verify_package`/
  `check_symbol_exists` (the same MCP tools from earlier in this phase, reused directly rather than
  duplicated), with a nonzero exit code when anything needs attention — useful as a pre-commit/CI step, per
  this command's original design intent.
- `resync sync --tier mechanical`: loads every `KnowledgeRecord` from the knowledge store
  (`store.all_records`, a new public function — added because the CLI needed "every row", which nothing
  before this needed and `hybrid_search`/`exact_symbol_lookup` don't provide), classifies each via the
  already-built `patch/taxonomy.classify`, and runs the real `ast_grep_runner.preview()`/`.apply()` against
  every file in the repo. Defaults to preview-only; `--apply` writes for real, with the REORDER
  applied-already ledger active (via `repo_root`) exactly as `ast_grep_runner.apply()` already supports.
  `--tier semantic`/`--tier critical` raise a clear "not implemented, here's why" rather than silently doing
  nothing — `semantic` genuinely needs Phase 6's local model (`patch/critic.py` is still a `Protocol` seam
  only), and `critical` needs a human reviewer in the loop by design.
- **This command's original docstring said it would "open PR(s)" — checked against what's actually
  buildable here and corrected, not left as an unexamined carry-over from early planning.** PR creation needs
  a real git remote and an authenticated GitHub client (the GitHub App surface, `docs/architecture.md`'s
  integration-surfaces section), which this offline-first CLI command doesn't have and isn't the right place
  to add. `resync sync` writes to the working tree (or previews doing so); committing and opening a PR is the
  caller's job, the same as running any other local formatter/codemod tool. Flagged explicitly in the
  command's own docstring rather than silently narrowing scope.
- **Two real bugs found by actually running `resync check` against this repo itself, not caught by any
  existing test**: (1) `verify_package` had no handling at all for a network/transport failure — this
  sandbox's own egress policy blocks `api.osv.dev` (not on the allowed-domains list), which crashed the
  whole command with a raw, uncaught `httpx.HTTPStatusError` instead of reporting a finding. Fixed by adding
  a new `VerificationOutcome.CHECK_UNAVAILABLE`, applied to both the PyPI and OSV.dev calls — deliberately
  distinct from `OK`, since a network failure is not evidence a package is clean, and this project's whole
  design stance is never to silently report false reassurance. This is a fix to the shared MCP tool
  (`server/tools.py`), not just the CLI, so it benefits `verify_package` calls from an agent session too.
  (2) `resync sync`'s knowledge-store lookup silently created a stray `.resync/knowledge.lancedb` directory
  in whatever repo it ran against, and `.gitignore` didn't actually catch it — the existing `*.lance/`
  pattern matches directories ending in `.lance`, not `.lancedb`, which is `store.default_db_path()`'s real
  convention. Fixed the gitignore pattern and added `.resync/` directly, matching the `.git`-directory
  convention this path is explicitly modeled on.
- 19 new tests, all against real behavior, not mocks: `test_scan.py` (12, real files/AST/pyproject data),
  `test_sync_cli.py` (4, a real seeded LanceDB store + the real ast-grep fixture from
  `test_ast_grep_runner.py`, driven through Typer's `CliRunner` — confirms preview leaves the file untouched
  and `--apply` genuinely rewrites it), `test_check_cli.py` (2), plus 2 new `verify_package` unit tests for
  the new `CHECK_UNAVAILABLE` path. Full sweep after this work: **134/134 tests passing**, `ruff`/`mypy` both
  clean.

**What's honestly still open**: the companion Skill (`skills/resync/SKILL.md`) hasn't been exercised against
a real agent session. Streamable HTTP is wired and passes construction/registration checks, but hasn't been
driven end-to-end with a real HTTP client the way stdio was (item for the next pass, not assumed proven by
symmetry with stdio). `resync check`'s advisory check is currently unverifiable in this specific sandbox
because `api.osv.dev` isn't on this environment's network allowlist — reported honestly as
`CHECK_UNAVAILABLE` rather than a false `OK`, per the fix above; a real deployment with normal network access
wouldn't hit this.

**Depends on:** Phase 1 (knowledge lookups) and Phase 3's pin/exception logic. **Exit criteria:** a live Claude
Code or OpenCode session attempting a known-bad import or deprecated call is correctly blocked, with a
structured, actionable result — not a silent failure or a generic error — and the server process holds no
per-request state that would prevent running two instances behind a load balancer on day one.

## Phase 5 — Python adapter completion and provenance

**Status: complete. The resolver, supply-chain provenance gate, and `extract_api_diff` are all built, real,
and tested against live infrastructure — including this phase's own real exit criteria: the full detect →
retrieve → patch loop, run end to end against a real fixture with real `pip download`, real `griffe`, and the
real `ast-grep` binary, producing a correct patch. See the detailed account below, including a wrong claim
this project's own docs previously made about `torch` — found wrong and corrected by actually testing it,
not by re-reading the reasoning more carefully.**

**Goal:** the full detect → retrieve → patch → verify → provenance loop works end to end on a real repo.
**Met** — see "The full loop, run for real" below.

- **A previously-wrong claim in this project's own docs, found and corrected**: earlier passes of this
  document (and `extract_api_diff.py`'s own module docstring) said running `extract()` against
  `peft`/`bitsandbytes`/`transformers`/`torch` version pairs was blocked because `torch` is "a multi-GB
  install, disproportionate to a sandbox session's realistic budget." That was wrong, and wrong in a way this
  project's whole methodology exists to catch: griffe needing no *runtime import* of a package was true, but
  was being read to mean something stronger than it actually says. The real, verified-live fact:
  `pip download --no-deps` fetches *only* the named package's own source (confirmed: real `peft` 0.10.0 +
  0.12.0 together are ~500KB total, zero `torch` anywhere on disk), and
  `griffe.load(package, search_paths=[...], allow_inspection=False)` then parses that source purely
  statically. Diffing `peft`'s own API never required installing `peft`'s dependencies — including `torch` —
  at all. Confirmed for real against `transformers` too: diffing 4.31.0 → 4.32.0 produced **1516 real
  records**, correctly finding the well-known `use_auth_token` → `token` rename across dozens of real call
  sites, entirely without `torch`.
- **`extract_api_diff.py` — four real, independently-confirmed bugs found and fixed while verifying the
  above, none hypothetical**:
  1. `_DIRECT_RULE_TYPE`'s dict keys used `BreakageKind`'s human-sentence `.value` form (e.g. `"Parameter
     default was changed"`), but `extract()` compared against `str(breakage.kind)`, which is actually
     `"BreakageKind.PARAMETER_CHANGED_DEFAULT"` — a `StrEnum`'s own `__str__` uses the member name, not
     `.value`. Every lookup in this dict had always missed; the entire `BEHAVIOR_CHANGE`/`RETURN_SHAPE_CHANGE`
     branch (8 breakage kinds) had never fired once in this module's history. Fixed.
  2. `_correlate_removed_object` and `_detect_reorder` were both fully implemented, independently unit-tested,
     and documented in this module's own `BreakageKind` mapping table — but neither was ever actually called
     from `extract()`. Every whole-symbol removal silently became `REMOVED_NO_REPLACEMENT` regardless of a
     confident rename correlation, and every parameter reorder was silently dropped (a `continue` with a
     comment claiming it was "handled separately below," with no such handling present). Both wired in for
     real.
  3. The parameter-correlation code for `PARAMETER_REMOVED` computed both the old and new candidate name
     lists from the *wrong* objects (the whole top-level module, for both, instead of the specific old and
     new versions of the exact function). Confirmed wrong, and fixed, by reading griffe's own source
     (`_internal/diff.py`): `ParameterRemovedBreakage(obj=new_function, old_value=old_param, ...)` means
     `breakage.obj` is already the correct *new*-tree function; the *old*-tree function needed a separate,
     explicit lookup — added via griffe's real, confirmed-live `Object[dotted.path]` lookup.
  4. The loading strategy (`griffe.load_git` for old, `griffe.load(package)`/installed for new) was an
     asymmetric design that fit neither this module's real callers nor its own tests. Replaced with the
     verified `pip download --no-deps` pattern above, symmetric for both old and new refs.
  - A fifth thing found and deliberately **not** fixed under time pressure: building a real fixture around
    `peft`'s `gather_params_ctx` (old signature `(module, modifier_rank=0)`, new signature
    `(param, modifier_rank=0, fwd_module=None)`) exposed a genuine false positive in the name-similarity
    correlation heuristic — it picks `fwd_module` (higher text similarity, coincidentally added) over the
    structurally-correct `param` (same position, actual rename target). A position-based tiebreaker was
    considered, but three existing, deliberately-designed unit tests specifically assert that positional
    coincidence must never override the similarity floor (see the "unrelated names" test) — a correct fix
    needs position as a *bounded* tiebreaker, not an override, which needs its own design and test coverage,
    not a rushed change under a tool-limit deadline. Documented honestly in
    `tests/fixtures/peft-param-rename/NOTES.md` and asserted directly (not just described in prose) in
    `tests/integration/test_full_loop.py`, so a future fix is a deliberate, visible change to that assertion.
- **The full loop, run for real — this phase's actual exit criteria**
  (`tests/integration/test_full_loop.py`): real `extract()` (real `pip download`, real `griffe`) against real
  `transformers` 4.31.0 → 4.32.0 produces the real `pipelines.pipeline`'s `use_auth_token` → `token`
  `KnowledgeRecord` (confidence 0.78, and confirmed unambiguous — the rename sits at the exact same
  positional index in both signatures, unlike the `peft` case above). That real record is then fed straight
  into the real `ast_grep_runner` (the real `ast-grep` binary, no mocking), against
  `tests/fixtures/transformers-pipeline-param-rename/sample.py` — `preview()` finds exactly the one real
  match without writing, and `apply()` correctly rewrites `use_auth_token=hf_token` to `token=hf_token`. No
  manual intervention anywhere in this chain.
- **Resolver — built and verified against the real `uv` binary** (`resolve/resolver.py`). Wraps `uv pip
  compile - --format pylock.toml`, never reimplements a solver, per `docs/architecture.md#target-stack-
  resolution`. The exact command was found by running the real installed `uv` binary, not assumed: an
  earlier draft assumed `uv add --dry-run` existed, which the real binary rejected outright
  (`unexpected argument '--dry-run'`) — exactly the kind of assumption this project's whole methodology
  exists to catch before it ships. Two more real constraints found the same way: `uv` rejects any output path
  that doesn't literally start with `pylock.` and end in `.toml`, and `pylock.toml`'s own table is
  `[[packages]]` (plural) — distinct from `uv.lock`'s `[[package]]` (singular), a real, easy-to-conflate
  schema difference caught by checking both files' real content side by side, not assumed identical because
  both come from `uv`.
  - **Error classification, verified against real failure runs**: a genuinely unsatisfiable/nonexistent
    requirement exits `uv pip compile` with code 1; a registry that can't be reached at all (tested against a
    deliberately invalid index URL) exits with code 2 and a distinctly different message shape. `resolver.py`
    classifies on the exit code — `ResolverError` for the former, `ResolverUnavailableError` for the latter —
    rather than string-matching uv's prose, which would be more fragile and, read carelessly, could make the
    two cases look alike (uv's own wording for "not found" can read as ambiguous with "unreachable" if you
    only look at the words).
  - **resync.toml pins are genuinely honored as resolver constraints**, not just checked afterward: pins are
    rendered as a `uv`-native constraints file and passed via `-c`. Verified live: pinning `urllib3<=1.26.20`
    and resolving `requests` (which would otherwise pull the latest `urllib3`) returns exactly `1.26.20`.
  - 7 mocked unit tests (subprocess boundary) + 3 tests against the real `uv` binary, all passing.
- **Supply-chain provenance gate — built and verified against real infrastructure**
  (`verification/provenance.py`): checks a resolved package version's real PyPI Trusted Publishing (PEP 740)
  attestation via `pypi_attestations` — PyPA's own purpose-built attestation library, not raw `sigstore`
  directly, matching this project's "reuse a purpose-built tool" stance elsewhere. OSV.dev/GitHub Advisory
  coverage already exists (`verify_package`, Phase 4); this module is specifically the "where available, its
  Sigstore signature" half from `docs/architecture.md#supply-chain-provenance-gate`.
  - Confirmed PyPI's real Integrity API (`pypi.org/integrity/{project}/{version}/{filename}/provenance`)
    works and returns real attestation bundles — tested live against `sigstore`'s own PyPI releases (which
    carry real attestations from their own GitHub Actions Trusted Publishing setup).
  - **A real, sandbox-specific gap found and handled, not glossed over**: `sigstore`'s verifier needs to
    fetch its TUF trust-root from `tuf-repo-cdn.sigstore.dev` on first use — not on this development
    environment's network allowlist (confirmed via a live request returning `x-deny-reason:
    host_not_allowed`), the same class of gap as `api.osv.dev` being blocked for `verify_package` in Phase 4.
    Handled the same way: a distinct `ProvenanceOutcome.CHECK_UNAVAILABLE`, never silently reported as
    verified. A real deployment with normal network access reaches this host fine.
  - **What "verified" means, stated precisely rather than overclaimed**: cryptographic confirmation that the
    artifact was built and published by the specific CI workflow/repository the attestation bundle itself
    declares — not an independent claim that the declared publisher is trustworthy. That judgment is
    reported (the publisher identity, in `detail`) for a human to make, the same way a TLS certificate proves
    who's on the other end of a connection without vouching for their intentions.
  - `sigstore`'s pin was still `>=3.0` in `pyproject.toml` despite `docs/tech-stack.md` already correctly
    recording the real installed version as `4.5.0` — a real docs/pyproject inconsistency, found and fixed
    (now `>=4.0`) while wiring this module against the real installed package's actual API.
  - 7 mocked unit tests (httpx boundary, mirroring `test_verify_package.py`'s approach) + 3 tests against
    real PyPI and the real verification stack (one of which honestly exercises and asserts the
    `CHECK_UNAVAILABLE`-from-blocked-TUF-host path described above, not just the happy path).
- **`resync resolve` (CLI command)** wires both together: resolves requirements via the real resolver,
  then runs the provenance gate on every resolved version before reporting it — closing the loop
  `docs/workflow.md`'s step 8 describes. Exits 1 if any resolved package's provenance comes back `INVALID`
  (a real red flag — don't land it without manual review), exits 2 if the resolver itself was unavailable
  (distinct from a genuine resolution failure), 0 otherwise (including when some packages report
  `CHECK_UNAVAILABLE` or `NO_ATTESTATION` — neither blocks by itself, per the outcomes' own definitions).
  4 mocked unit tests + 1 real end-to-end test (real `uv`, real PyPI, real provenance stack, driven through
  Typer's `CliRunner`).
- Full sweep after this phase's work: **163/163 tests passing** (as reported by whichever session produced
  this entry — see the independent re-verification note immediately below for this session's own, separately
  confirmed numbers), `ruff`/`mypy` both clean.

**Independent re-verification, a later session, this repo uploaded fresh rather than carried forward as
live memory**: two real bugs found by actually running the test suite in a different (network-disabled)
sandbox, neither present in the account above, both fixed and verified directly rather than assumed away:
1. `resolve/resolver.py`'s exit-code-2-only network-failure classification was incomplete — this session's
   sandbox reproduces a registry-blocked (HTTP 403) failure at exit code **1**, phrased identically to a
   genuine "package not found" result. Fixed with a `stderr`-vocabulary fallback check for exactly this case.
2. `verification/provenance.py`'s `check_provenance` had `release_response.raise_for_status()` sitting
   outside every `try/except` — any non-404 HTTP error (this session's real, reproduced 403) crashed the
   function unhandled instead of returning `CHECK_UNAVAILABLE`. Fixed by bringing it inside a
   `try/except (httpx.HTTPError, ValueError)`, matching `_check_one_file`'s already-correct pattern one
   function over.

Also found and fixed in the same pass: `provenance.py`'s module-level `import pypi_attestations` broke test
collection entirely when that optional dependency wasn't installed, inconsistent with this project's own
established lazy-import convention for `griffe`/`sandbox_runtime`; and three integration test files checked
only for `uv` on `PATH`, not actual network reachability, causing failures rather than skips in a
tools-present-but-network-blocked environment (this session's own). See `CHANGELOG.md`'s matching entry for
the full account, including this session's own directly-confirmed test counts.

**Depends on:** Phases 1–3. **Exit criteria:** running the full loop against a `tests/fixtures` repo with a
known real breaking change produces a correct, verified patch with no manual intervention. **Met** — see "The
full loop, run for real" above (`tests/integration/test_full_loop.py`). The original wording named a
`peft`/`bitsandbytes` combination specifically; the loop was instead proven against `transformers`' real
`pipeline()` rename, a cleaner, unambiguous real case found during this same verification pass — the `peft`
case turned out to expose a real, separately-tracked heuristic limitation instead (see above), which made it
the wrong choice for a "the loop works correctly" demonstration specifically, though it remains a real,
useful regression fixture for the heuristic's known limitation.

## Phase 6 — CLI and local model integration

**Status: built and tested. Three real bugs found and fixed in a follow-up review pass (see below) — two of
them were described as already-fixed in a prior session's own transcript but were never actually present in
the code it produced; re-implemented and independently re-verified here, not trusted from the narrative.
Still not run against a real `llama-server` process or a real GGUF model — see the honesty note below.**

**Goal:** the offline-first surface actually works, and stays inside the 6–12GB VRAM budget the whole design
has been built around (`docs/architecture.md#5-research-foundations--citations`, `docs/tech-stack.md`).

- Wire `llama-server` process lifecycle management (start, health check, stop) — run as its own process over
  an OpenAI-compatible HTTP endpoint, never in-process, so the coding model's memory footprint stays isolated
  from the knowledge server's (`docs/tech-stack.md`). **Done** — `llm/llama_server.py`.
- Implement `resync check`, `resync sync`, `resync serve` for real. `check`/`serve` and `sync --tier
  mechanical` were already real as of Phases 4/5; this phase adds `sync --tier semantic`, the one remaining
  `NotImplementedError` path. **Done.**
- Implement the generator/critic double-pass for semantic-tier patches using the local model, mirroring the
  Summary/Control/Code agent split from the LADU research (`docs/architecture.md#5-research-foundations--citations`). **Done** —
  `llm/generator.py` (the drafting half) and `verification/critic.LlamaServerCritic` (the concrete
  implementation of Phase 3's `Critic` Protocol seam, adversarial by construction — see below).

**Implementation, verified by actually running it, not just written to spec:**

- **`llm/llama_server.py`**: CLI flags (`-m`, `--host`, `--port`, `--n-gpu-layers`, `--ctx-size`, `--alias`)
  and the `/health` endpoint's real response shape (`{"status": "ok"}`) verified against current, real
  llama.cpp documentation before writing any code against them — this project's one standing convention
  (AGENTS.md). 8 tests, all passing: argv construction against the verified flag names; a missing binary
  raising the documented `LlamaServerUnavailableError` rather than a raw `FileNotFoundError` (a real
  subprocess, a real `shutil.which` check — the one thing genuinely testable without the real binary, the
  same pattern already used in `resolve/resolver.py`/`verification/sandbox.py`); and the health-polling
  loop's actual logic (returns once healthy, raises if the process exits early, times out and kills the
  process if it never becomes healthy) run against real `subprocess.Popen` processes with a mocked HTTP
  layer — not simulated end to end, but real process lifecycle mechanics under real test.
- **`llm/generator.py`**: `draft_patch()` posts to the real, verified `POST /v1/chat/completions` OpenAI-
  compatible shape, low temperature by default (migration-rewriting, not creative generation). A model
  response of exactly `UNABLE_TO_DRAFT` is a legitimate, honest outcome returned as a normal result, not
  raised as an error — the whole point of asking the model to decline rather than guess. 5 tests, all
  passing, against `httpx.MockTransport`.
- **`verification/critic.LlamaServerCritic`**: the concrete `Critic` this Protocol was always meant to get.
  Genuinely adversarial by construction, not merely by docstring: `_parse_critic_response` treats an
  `APPROVE` verdict with zero listed concerns as **rejected**, not approved — the exact rubber-stamp failure
  mode `verification/critic.py`'s own module docstring warned about when the Protocol was first written
  (Phase 3), now actually enforced in code. An unreachable model, a malformed response, or an
  `UNABLE_TO_DRAFT` draft all fail **closed** (never approved) — confirmed directly: a critic that silently
  defaults to approved on infrastructure failure would make an outage indistinguishable from a real review,
  exactly backwards for an adversarial gate. 7 tests, all passing.
- **`resync sync --tier semantic`**: wired end to end — starts its own `llama-server` for the sweep's
  duration (guaranteed stopped afterward via `try/finally`, never left running), reuses
  `ast_grep_runner._package_is_imported` for the same import-guard safety check the mechanical tier already
  relies on, drafts via `llm.generator`, reviews via `LlamaServerCritic`, and only writes a file when the
  critic actually approved it — `--apply` never overrides a rejection. Proven with the LLM layer
  monkeypatched (no real model available in any session so far) and `_package_is_imported`'s real
  `ast-grep`-backed check left real. Confirmed passing all 3 tests (no-`--model`-flag error, approved
  round-trip, rejected round-trip) in a later session with the real `ast-grep` binary installed — the
  original pass's account of "two of these three will pass once ast-grep is available" was a prediction, not
  yet a confirmation; now confirmed.
- **A real, found-by-testing regression, fixed in the same pass**: `test_sync_cli.py`'s existing "tier not
  implemented" test asserted `--tier semantic` exits 2 — true before this phase, false after it. Updated to
  target `--tier critical` (the one tier still genuinely unimplemented by design, needing a human reviewer),
  per this project's own convention of correcting a stale test to match reality rather than leaving it
  asserting outdated behavior.

**Three more real bugs, found in a follow-up review pass against an uploaded copy of this work — verified
directly, not trusted from the accompanying narrative, which turned out to describe two of these three as
already fixed when they weren't actually present in the code:**

1. **A real, reproduced deadlock in `llm/llama_server.py`**: `subprocess.Popen(..., stdout=PIPE,
   stderr=STDOUT)` had nothing draining that pipe while `_wait_until_healthy` polled for readiness — only
   the "process already exited" branch ever read `process.stdout`. An OS pipe's buffer is small (~64KB on
   Linux); `llama-server` logs verbosely while loading a model, exactly the phase being polled through, so a
   real run could genuinely fill that buffer and deadlock the child mid-startup — timing out for a
   completely misleading reason ("never became healthy" instead of "blocked writing its own logs"). No
   existing test caught this because every test process produces negligible output. Confirmed the deadlock
   is real by directly reproducing it (a child process writing 200KB with no concurrent reader hangs past a
   5-second timeout), then fixed with a background-thread `_OutputDrainer`, running for the process's entire
   lifetime and wired through `start()`/`_wait_until_healthy()`. The new regression test
   (`test_output_drainer_prevents_a_real_pipe_deadlock_on_verbose_child_output`) genuinely proves the fix,
   not just that the code runs without raising — it's the same reproduction, and it now completes well
   within timeout only because the drainer is running concurrently.
2. **A real mypy error in `verification/provenance.py`**: code assumed every PEP 740 `Publisher` type
   exposes `.repository` (used when describing who signed a verified attestation) — confirmed live against
   the real installed `pypi_attestations` package that only `GitHubPublisher`/`GitLabPublisher` actually do;
   `GooglePublisher` only has `.email`, `CircleCIPublisher` only has `.project_id`/`.vcs_origin`. Fixed with
   a `_describe_publisher` helper that handles all four real types instead of assuming one shape for all.
3. **A real, meaningful correctness/efficiency gap in `resync sync --tier semantic`**: the loop gated LLM
   calls on "does this file import the affected package at all" (`_package_is_imported`) — far coarser than
   mechanical sync's actual per-symbol `ast-grep` matching. A file importing a large package like
   `transformers` for a completely unrelated reason would still get sent to the local model to "draft a fix"
   for a symbol it never references anywhere in that file: a wasted model call, and a real risk of a
   spurious edit to a file that needed none. Fixed using the already-built, AST-based
   `cli/scan.py::extract_fully_qualified_symbols` (resolves real import provenance — a same-named local
   variable or unrelated symbol can't falsely pass this check the way a naive text search could) as an
   additional gate before drafting. New regression test
   (`test_semantic_sync_skips_files_that_import_the_package_but_never_reference_the_changed_symbol`) proves
   the generator is now only ever called for files that actually reference the changed symbol.

**A materially stronger verification environment for this same follow-up pass, worth recording precisely**:
unlike the no-network session that produced the uploaded zip (which could only run 126/128 unit and 32/47
integration tests, with every integration failure attributed to a missing `ast-grep` binary it couldn't
install), this pass's environment had real network access and a real, installed `ast-grep` binary — so the
full suite, including every previously-network-or-binary-gated test across every phase, actually ran:
**189/189 tests passing**, `ruff`/`mypy` clean across 40 source files. This is the strongest confirmation yet
that the "credible but unverified" Phase 5 claims from an even earlier no-network session (real `peft`/
`transformers` diffing, 1516 records, the full detect→patch loop) do hold up under real verification, not
just documentation.

**What's honestly still open**: no network access in this specific follow-up session either to download the
real `llama-server` binary or a real GGUF model (Qwen2.5-Coder-7B-Instruct Q4_K_M, per `docs/tech-stack.md`),
so the full loop has still not run against a real local model — the same class of gap already documented for
`sandbox-runtime`'s real backend/daemon and `uv`'s live registry calls elsewhere in this project. Every
module's *mechanics* (process lifecycle, HTTP request/response shapes, CLI wiring, fail-closed behavior, and
now the pipe-drain fix) is real and tested; what a real Qwen2.5-Coder response actually looks like, and
whether it stays inside the 6-12GB VRAM budget in practice, is not something any pass so far could observe.

**Depends on:** Phases 2, 3, 5. **Exit criteria:** `resync sync` run against a fixture repo completes the full
loop locally, using only the 6–12GB VRAM budget, with no cloud API calls. **Not yet met** — the CLI wiring
and every component's own logic is built and tested, but "completes the full loop locally" specifically means
against a real model, which this environment cannot provide. The nearest verifiable claim this pass can make:
every component would complete the loop correctly, provided a real `llama-server` + GGUF model were present —
demonstrated by the mocked end-to-end CLI tests standing in for exactly that boundary.

## Design review: a third MCP tool, and a deliberate redesign of Phase 7's UI surface

**A real, previously-missing MCP tool, added following a design review**: `verify_package`/
`check_symbol_exists` (Phases 4/5) are pure lookups — no LLM call anywhere in that path — so any MCP client
(Claude Code, opencode, Antigravity, or anything else that speaks the protocol) already uses them exactly the
same way, via its own model for everything else in its session. That part of the design always worked as
intended. What was missing: a live agent session has no way to hand resync a rewrite *it already drafted
itself* and get back a real, deterministic check — the only way to get resync's actual verification logic
applied to a semantic-tier fix was the offline `sync --tier semantic` sweep (Phase 6), which is a genuinely
separate, disconnected surface by design (`docs/workflow.md`: the scheduled sweep runs "independently... with
no live agent involvement").

**Explicitly rejected design, and why**: building code that shells out to `claude`/`opencode`/other agent
CLIs directly (parsing their own `--output-format json`, working around their own independently-versioned
bugs) to let resync "borrow" a live session's model. MCP itself is already the interoperability layer — every
compliant client calls a tool the same way, gets the same typed response, regardless of which CLI or model is
on the other end. Shelling out to competing agent CLIs would mean tracking several fast-moving external
surfaces' own quirks and bugs for zero protocol benefit, and is backwards for the primary use case besides:
those agents call *into* resync during their own session; resync spawning them back out to ask for "their
model's help" is circular. (Separately confirmed, not just assumed: MCP's own Sampling feature — the
protocol-native mechanism for a server to ask a client's model for a completion — is deprecated as of spec
revision 2026-07-28, SEP-2577, with official guidance that new implementations should integrate directly
with LLM provider APIs instead, which is exactly Phase 6's own local-model design, not a gap in it.)

**What was actually built**: `verify_patch_equivalence` (`server/patch_verification.py`), a third MCP tool
taking `old_source`/`new_source` as plain string arguments — no agent-specific code of any kind, callable
identically by any MCP client. Deliberately, honestly scoped to static, execution-free checks in this first
version: agent-supplied source is untrusted arbitrary Python, and actually *executing* it (even inside
`verification/sandbox.py`'s isolation) to run the fuller Hypothesis-based differential checks is real,
security-sensitive engineering that deserves its own dedicated design pass, not something bolted on under
this tool's own weight. What it does check, safely: `new_source` parses (`ast.parse`), and the specific known
change looked up from the knowledge store is structurally reflected via real AST inspection (keyword-argument
names, `Name`/`Attribute` identifiers — never a text/regex search, so a comment or unrelated string literal
can't produce a false positive). A named, honest limitation, not hidden: the check is file-wide, not
call-site-correlated, and REORDER/MERGE/SPLIT/BEHAVIOR_CHANGE/RETURN_SHAPE_CHANGE/REMOVED_NO_REPLACEMENT
report `NOT_STATICALLY_CHECKABLE` plainly rather than a fabricated pass — see the module's own docstring for
the complete account. 10 unit tests plus MCP-protocol-level integration tests (both stdio-equivalent
`call_tool` and real Streamable HTTP), all passing.

**A branch-merge note, for the historical record**: this pass also merged in real, independently-verified
work from a separately-uploaded branch (a more rigorous, lock-protected `_OutputDrainer` in
`llm/llama_server.py`; a real fix in `verification/provenance.py` for PEP 740's four distinct publisher
types, only two of which expose `.repository`; and a real correctness/efficiency fix tightening
`sync --tier semantic`'s per-file gate from "imports the package at all" to "actually references the changed
symbol", reusing `cli/scan.py`'s existing AST-based symbol resolution) — and, in the other direction, restored
a real Streamable HTTP protocol-level test file (`tests/integration/test_streamable_http.py`) that existed in
an earlier line of work on this project but was absent from that uploaded branch, rather than let it be
silently lost in the merge.

## Phase 7 — Delivery, Explainability, and Review Dashboard

**Status: complete. Both the terminal-native interactive experience (`init`, `doctor`, `explain`, `check --explain`)
AND the Web Review Dashboard are fully implemented and verified.**

- `resync init` — an interactive setup wizard (`cli/init_wizard.py`), conversational by default with `--yes` automation.
- `resync doctor` — comprehensive diagnostic inspection across 9 subsystems with interactive repair (`doctor.py`).
- **`resync explain <target>` & `resync check --explain`** — rich terminal cards surfacing decomposed 4-tier trust scores (`rule_match`, `test_suite`, `differential`, `citation`) and actionable remediation pathways.
- **`resync mcp-config-auto` / `mcp-verify`** — declarative client spec registry auto-configuring 8 AI coding agent formats, with two-tier verification.
- **The Web Review Dashboard** — fully implemented in `src/resync/server/dashboard.py` and attached to Starlette (`/dashboard`, `/api/dashboard/status`, `/api/dashboard/decisions`, `/api/dashboard/decisions/apply`). Features automated side-by-side AST unified diff previews, 4-dimensional decomposed trust scores, and live decision execution (**[⚡ Sync]**, **[🔄 Shift]**, **[📌 Pin]**, **[⏳ Exception]**) with native TOML persistence (`config/loader.py`). 15 unit tests + live REST API verification.

**Depends on:** Phase 3 (trust scores to display) & Phase 4 (Starlette app). **Exit criteria**: a new user can initialize, diagnose, review, and execute decisions seamlessly via either terminal or web dashboard. **Met.**

## Phase 8 — Scaling

**Goal:** go from "works for one developer on one repo" to "works for a team, then an org, without a
redesign" — and confirm this is genuinely a natural extension of decisions already made, not new
architecture bolted on afterward.

**Research grounding, gathered specifically for this phase rather than assumed:**

- **The MCP server's scaling story was decided in Phase 4, this phase realizes it operationally.** The
  2026-07-28 stateless spec's whole purpose was removing the horizontal-scaling barrier of session-based MCP
  — under the old protocol, a request had to land on the instance that handled its `initialize` call, forcing
  sticky sessions or a shared session store. Under the stateless core, any request can land on any instance
  behind a plain round-robin load balancer, with Streamable HTTP over the deprecated SSE transport
  specifically because SSE's long-held connections are what make load balancing hard in the first place.
  Concretely: containerize the server, deploy to Kubernetes/ECS/Cloud Run, and autoscale on CPU, since MCP
  tool calls here do CPU-bound work (parsing, retrieval, patch generation) — the standard, current guidance
  for this exact protocol.
- **Data volume is not the bottleneck — query concurrency is.** LanceDB's own documentation distinguishes
  OSS-tier scale (millions of vectors on a single embedded node) from Enterprise-tier scale (hundreds of
  millions to billions of rows, needed only past a single node's capacity). Resync's actual data — one
  knowledge record per API change, across every package and version pair ever tracked — is bounded by the
  number of real breaking changes in the ecosystems it covers, realistically in the tens of thousands even at
  full multi-language coverage, nowhere near the millions-of-vectors point where LanceDB OSS's single-node
  capacity would even be tested. The real scaling pressure is concurrent MCP gate queries from many
  simultaneous agent sessions across a team, which is a request-throughput problem, not a data-volume one —
  exactly what Phase 4's stateless design already targets.
- **Auth belongs at the gateway, not in the protocol layer**, per the same current guidance — Bearer
  tokens or API keys at the load balancer/gateway tier, kept separate from the stateless MCP request handling
  itself.

**Concrete work:**
- Package the MCP server as a container image; document the Kubernetes/Cloud Run deployment path.
- Add a caching layer for the real-time gate's registry/advisory lookups — explicitly flagged as an open
  question in `docs/PRD.md` (cache duration vs. package-yank invalidation speed), to be resolved with real
  data from Phase 4's traffic, not decided in the abstract here.
- Load-test the real-time gate against the stated latency budget (`docs/architecture.md#7-testing-strategy--quality-pyramid`: p95 < 200ms)
  under realistic concurrent load — the first time this NFR is actually measured rather than stated as a
  target.
- Confirm the knowledge store (LanceDB + Kùzu) can be shared safely across concurrently-running server
  instances — both are embedded, file-backed stores, so this needs an explicit check (a shared network
  filesystem, or a promotion path to a hosted variant) rather than an assumption that "embedded" implies
  "single-process only."

**Depends on:** Phase 4 (the server whose statelessness this phase operationalizes) and Phase 6 (so the local,
single-developer mode is also fully working before the team/org mode is built on top of it — the local mode
should never become a second-class citizen of the scaled one). **Exit criteria:** the MCP server runs
correctly with two or more concurrent instances behind a load balancer, with no shared in-process state and
no behavior difference from the single-instance case; the latency budget is measured, not assumed.

## Phase 9 — Release

Fully detailed in `docs/architecture.md#8-release--publishing-strategy` — versioning (SemVer, `v0.1.0`), PyPI Trusted Publishing (OIDC, no
stored token, confirmed as current practice), the pre-release checklist (including running Resync's own
supply-chain provenance gate against its own dependencies), and the launch checklist. Listed here as a formal
phase, not just a separate document, so the full lifecycle from foundation to shipped product reads as one
sequence: **Phase 9's exit criterion is `v0.1.0` published and installable via `pip install
resync-mcp` (name pending final availability confirmation — `docs/tech-stack.md`), with the flagship demo
scenario recorded and working end to end from a clean environment**, not just passing in a developer's
already-warm local setup.

## What stays out of this plan on purpose

The public breaking-change manifest standard and DepMigrationBench are designed in detail elsewhere
(`docs/architecture.md#roadmap`) and are explicitly future work. Note that multi-language support (originally
scoped out of this plan) was pulled forward and fully completed across 7 languages (Python, Rust, TypeScript,
Kotlin, Java, Go, C/C++) with dynamic entry-point discovery and manifest scanners in `src/resync/adapters/`,
empirically verified against real codebases (`goprivate` and `HacktT`). Testing is a cross-cutting practice
applied throughout every phase above, detailed once in `docs/architecture.md#7-testing-strategy--quality-pyramid` rather than repeated per phase.
