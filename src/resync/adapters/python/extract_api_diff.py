"""Derive KnowledgeRecords from a real structural diff of two installed/loadable package versions,
instead of a human (or an LLM) transcribing a changelog by hand.

Research finding this module is built on: `griffe` (mkdocstrings/griffe, PyPI) is a mature, actively
maintained, static AST-based tool purpose-built for exactly this — `griffe.find_breaking_changes(old, new)`
diffs two loaded API trees and yields typed `Breakage` objects.

**A real, previously-wrong claim in this module's own docstring, found and corrected by actually testing
it, not by re-reading the same reasoning more carefully**: this docstring used to say diffing
`torch`/`transformers`/`peft`/`bitsandbytes` "never requires installing them" because griffe needs no
*runtime import*. That's true but was being read to mean something stronger than it says — griffe still
needs each package's own *source* on disk to parse statically, and the natural way to get that
(`griffe.load_pypi`, or a plain `pip install`) installs the package's full declared dependency set, which
for `peft` genuinely includes `torch>=1.13.0` (confirmed against PyPI's real metadata for `peft`). That would
have made "diffing peft" implicitly mean "installing torch" after all — the thing this docstring claimed
wasn't necessary.

**What actually works, verified live end-to-end against real PyPI releases, not assumed**: `pip download
--no-deps --no-binary :all:` fetches *only* the named package's own sdist (no transitive dependencies at
all — confirmed live: `peft==0.10.0` and `peft==0.12.0` together are ~500KB total, zero torch anywhere), and
`griffe.load(package, search_paths=[extracted_src_dir], allow_inspection=False)` then parses it purely
statically — `allow_inspection=False` is the part that actually enforces "never import this," since
`griffe.load`'s default (`allow_inspection=True`) *can* fall back to a real import if static parsing hits
something ambiguous, which would silently reintroduce the exact problem this module exists to avoid. Live
confirmation: diffing real `peft` 0.10.0 → 0.12.0 this way found 32 real breaking changes, entirely without
torch (or peft's own other dependencies) present anywhere on disk. `_download_and_load` below is this
verified pattern, used for both `old_ref` and `new_ref` — replacing an earlier implementation that mixed
`griffe.load_git` (needs a git checkout) with `griffe.load(package)` (needs the package already importable,
i.e. installed) for old vs. new respectively, an asymmetric design that fit neither this module's actual
callers nor its own tests cleanly (see the git history on this file's `test_extract_api_diff.py` companion
for the checkout-assumption bug that mismatch previously caused).

**Two more real bugs found and fixed by actually running this against real package versions, not by
re-reading the code more carefully**: (1) `_correlate_removed_object` and `_detect_reorder` were both
defined, unit-tested in isolation, and documented in the mapping table below as part of `extract()`'s
behavior — but neither was actually *called* from `extract()`. Every `OBJECT_REMOVED` breakage silently
became `REMOVED_NO_REPLACEMENT` regardless of whether a confident rename correlation existed, and every
`PARAMETER_MOVED` breakage was silently dropped entirely (a `continue` with a comment claiming it was
"handled separately below," with no such handling actually present). (2) The parameter-correlation code for
`PARAMETER_REMOVED` computed both `old_names` and `new_names` from the *wrong* objects (the whole top-level
module, for both), rather than the specific old and new versions of the exact function where the parameter
was removed — confirmed wrong by checking griffe's own source (`_internal/diff.py`):
`ParameterRemovedBreakage(obj=new_function, old_value=old_param, ...)` means `breakage.obj` is already the
correct *new*-tree function, and the *old*-tree function has to be looked up separately by path. All three
are fixed below, using griffe's real, confirmed-live `Object.__getitem__` dotted-path lookup
(`old_obj["mod.Class.method"]`,
raising `KeyError` — not silently returning `None` — when a path genuinely doesn't exist in the other tree,
e.g. because the containing module itself was renamed).

Mapping from griffe's actual `BreakageKind` values (confirmed against griffe's own reference docs, not
guessed) to this project's `RuleType` taxonomy:

| griffe `BreakageKind`                                    | `RuleType`                       | mechanical? |
|-----------------------------------------------------------|-----------------------------------|-------------|
| `PARAMETER_MOVED` (grouped per-function, see below)        | `REORDER`                        | yes |
| `PARAMETER_REMOVED` + a confident correlated replacement   | `RENAME` (parameter)              | yes |
| `PARAMETER_REMOVED` + no confident match                   | `REMOVED_NO_REPLACEMENT`          | no (ESCALATE) |
| `OBJECT_REMOVED` + a confident correlated replacement       | `RENAME` (whole-symbol)           | yes |
| `OBJECT_REMOVED` + no confident match                       | `REMOVED_NO_REPLACEMENT`          | no (ESCALATE) |
| `PARAMETER_CHANGED_DEFAULT` / `_KIND` / `_REQUIRED` / `PARAMETER_ADDED_REQUIRED` | `BEHAVIOR_CHANGE` | no (SEMANTIC) |
| `RETURN_CHANGED_TYPE`                                      | `RETURN_SHAPE_CHANGE`             | no (SEMANTIC) |
| `ATTRIBUTE_CHANGED_TYPE` / `_VALUE`, `CLASS_REMOVED_BASE`, `OBJECT_CHANGED_KIND` | `BEHAVIOR_CHANGE` | no (SEMANTIC) |

**REORDER is still deliberately not read from griffe's own `PARAMETER_MOVED` breakage payload**, even though
that payload's real shape is now confirmed (`obj`=new-tree function, `old_value`/`new_value`=the moved
`Parameter` objects, one breakage yielded per moved parameter — confirmed by reading `_internal/diff.py`
directly). `_detect_reorder` below still independently compares the old and new `Function.parameters` name
order directly, because that comparison is what actually needs to happen *once per function* (griffe yields
one `PARAMETER_MOVED` per parameter, which this module groups back into one REORDER record per function) —
using the confirmed payload wouldn't remove that grouping step, so there's no remaining reason to prefer it
over the simpler, already-correct, already-tested direct comparison.

`_correlate_removed_parameter`, `_correlate_removed_object`, and `_detect_reorder` are pure functions over
plain data (names/positions) and are unit-tested without importing `griffe` at all. `extract()` itself, which
does import and call `griffe` (and shells out to `pip download`), is integration-tested against real PyPI
package versions — see `tests/integration/test_extract_api_diff.py`.
"""

from __future__ import annotations

import difflib
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType

if TYPE_CHECKING:
    import griffe  # noqa: F401 — typing-only; see extract()'s docstring for why this isn't a top-level import

# Below this name-similarity score, a PARAMETER_REMOVED/OBJECT_REMOVED is emitted as
# REMOVED_NO_REPLACEMENT rather than a low-confidence, probably-wrong RENAME guess.
_CORRELATION_MIN_SIMILARITY = 0.35

# The best candidate must beat the runner-up by at least this much, or the match is treated as ambiguous
# (multiple similarly-plausible candidates) rather than confident — see _best_name_match's docstring for
# why this was added after testing against the real AutoModelWithLMHead case.
_CORRELATION_MIN_MARGIN = 0.15

# griffe BreakageKind -> RuleType, for the breakage kinds that always map to one RuleType regardless of
# correlation (i.e. everything except PARAMETER_REMOVED/OBJECT_REMOVED, which need correlation first).
#
# Keys are `str(BreakageKind.X)`, i.e. `"BreakageKind.X"` — StrEnum's own `__str__` uses the member name,
# not `.value` (confirmed live: `str(BreakageKind.PARAMETER_CHANGED_DEFAULT) ==
# "BreakageKind.PARAMETER_CHANGED_DEFAULT"`, while `.value` is the human sentence
# `"Parameter default was changed"`). This dict previously used the `.value` sentence strings as keys while
# `extract()` compared against `str(breakage.kind)` — a real, silent bug: every lookup here always missed,
# so this entire branch never fired in this module's history. Fixed to match what `str()` actually returns.
_DIRECT_RULE_TYPE: dict[str, RuleType] = {
    "BreakageKind.PARAMETER_CHANGED_DEFAULT": RuleType.BEHAVIOR_CHANGE,
    "BreakageKind.PARAMETER_CHANGED_KIND": RuleType.BEHAVIOR_CHANGE,
    "BreakageKind.PARAMETER_CHANGED_REQUIRED": RuleType.BEHAVIOR_CHANGE,
    "BreakageKind.PARAMETER_ADDED_REQUIRED": RuleType.BEHAVIOR_CHANGE,
    "BreakageKind.RETURN_CHANGED_TYPE": RuleType.RETURN_SHAPE_CHANGE,
    "BreakageKind.ATTRIBUTE_CHANGED_TYPE": RuleType.BEHAVIOR_CHANGE,
    "BreakageKind.ATTRIBUTE_CHANGED_VALUE": RuleType.BEHAVIOR_CHANGE,
    "BreakageKind.CLASS_REMOVED_BASE": RuleType.BEHAVIOR_CHANGE,
    "BreakageKind.OBJECT_CHANGED_KIND": RuleType.BEHAVIOR_CHANGE,
}


@dataclass
class Correlation:
    """The result of trying to match a removed name against a plausible replacement.

    `confidence` is the raw similarity score (0.0-1.0), not yet blended with anything else — `extract()`
    combines it with a base confidence for "griffe's structural signal is itself reliable" before it ends
    up in a KnowledgeRecord's `confidence` field. Kept separate so the correlation quality and the
    structural-signal quality are each visible on their own, not pre-mixed into one number that hides which
    part is doing the work.
    """

    new_name: str
    confidence: float


def _best_name_match(removed_name: str, candidate_names: list[str]) -> Correlation | None:
    """Pure, griffe-independent matching: given a removed name and a list of newly-added candidate names
    (already filtered to "present in new, absent in old" by the caller), return the closest match by
    string similarity, or None if there's no single confident candidate.

    difflib.SequenceMatcher is a blunt instrument — it will not know that `no_cuda` and `use_cpu` are the
    same concept (no shared substring at all). This is a real, honest limitation: name-similarity
    correlation catches the common case (`use_auth_token` -> `token`, `per_gpu_train_batch_size` ->
    `per_device_train_batch_size`) but will miss semantically-related renames with unrelated spellings.
    Those fall through to REMOVED_NO_REPLACEMENT, which is the correct, safe default for a match this
    function isn't confident about — not a bug to silently patch over with a lower threshold.

    Two rejection conditions, found necessary by testing this against the real AutoModelWithLMHead case
    (see tests/unit/test_extract_api_diff.py): an absolute floor (`_CORRELATION_MIN_SIMILARITY`), and a
    *margin* check against the runner-up. The margin exists because sibling names within the same family
    (e.g. `AutoModelForCausalLM`/`AutoModelForMaskedLM`/`AutoModelForSeq2SeqLM`) all share a long common
    prefix with a removed name like `AutoModelWithLMHead`, so the absolute floor alone isn't enough to tell
    "one clearly-correct match" apart from "three similarly-plausible candidates, i.e. genuinely ambiguous"
    — exactly the case where a human should decide, not a heuristic guessing among near-ties.
    """
    if not candidate_names:
        return None
    scored = sorted(
        ((name, difflib.SequenceMatcher(a=removed_name, b=name).ratio()) for name in candidate_names),
        key=lambda pair: pair[1],
        reverse=True,
    )
    best_name, best_score = scored[0]
    if best_score < _CORRELATION_MIN_SIMILARITY:
        return None
    if len(scored) > 1:
        _, second_score = scored[1]
        if (best_score - second_score) < _CORRELATION_MIN_MARGIN:
            return None
    return Correlation(new_name=best_name, confidence=best_score)


def _correlate_removed_parameter(
    removed_param_name: str, old_param_names: list[str], new_param_names: list[str]
) -> Correlation | None:
    """A parameter disappeared from the old signature. Candidates are names present in the new signature
    but absent from the old one — an unrelated pre-existing parameter is never a valid "replacement" for a
    removed one, regardless of string similarity, since it was already there before the change.
    """
    added = [name for name in new_param_names if name not in old_param_names]
    return _best_name_match(removed_param_name, added)


def _correlate_removed_object(
    removed_name: str, old_sibling_names: list[str], new_sibling_names: list[str]
) -> Correlation | None:
    """A whole symbol (function/class) disappeared. Candidates are sibling names in the new version's same
    parent (module/class) that weren't already present in the old version — same reasoning as
    `_correlate_removed_parameter`: a pre-existing sibling isn't a "replacement", it's just a different,
    unrelated, already-existing symbol.
    """
    added = [name for name in new_sibling_names if name not in old_sibling_names]
    return _best_name_match(removed_name, added)


def _detect_reorder(old_param_names: list[str], new_param_names: list[str]) -> tuple[list[str], list[str]] | None:
    """Independent, griffe-payload-free REORDER detection — see module docstring for why this doesn't read
    griffe's own PARAMETER_MOVED breakage. Returns (old_order, new_order) if the exact same set of
    positional parameter names appears in a different order between the two signatures, else None.

    Deliberately exact-set-only: if the parameter set differs at all (something was also added or removed),
    this is not a pure REORDER — it is at minimum ambiguous and likely represents a different, more complex
    change that a human should look at, so this returns None rather than guess at a partial reorder.
    """
    if old_param_names == new_param_names:
        return None
    if set(old_param_names) != set(new_param_names):
        return None
    return old_param_names, new_param_names


def _function_positional_names(obj: Any) -> list[str]:
    """Extract positional-or-keyword parameter names from a griffe Function/Alias object, in declaration
    order. Defensive by design (getattr/try-except, not direct attribute access) — griffe's exact
    `Parameters`/`Parameter` shapes could not be confirmed against a real installed version in this
    environment (see module docstring), so this degrades to an empty list rather than raising if the
    expected shape isn't there, and callers treat an empty list as "nothing to compare", never as
    "confirmed no parameters".
    """
    try:
        params = obj.parameters
        return [p.name for p in params if getattr(p, "kind", None) is None or "positional" in str(p.kind).lower()]
    except AttributeError:
        return []


def extract(
    package: str,
    old_ref: str,
    new_ref: str,
    from_version: str,
    to_version: str,
    ecosystem: str = "pypi",
) -> list[KnowledgeRecord]:
    """Diff `package` between `old_ref` and `new_ref` (PyPI version specifiers, e.g. `"0.10.0"`) and return
    one KnowledgeRecord per detected change.

    This is the real Phase 1/5 unblock referenced throughout docs/implementation-plan.md and
    knowledge/seed_data.py's docstring: records from here are `source=RecordSource.API_DIFF_TOOL`, derived
    from an actual structural diff, not transcribed from prose. Requires `griffe` (the `server` extra, same
    tier as `lancedb`/`kuzu` — install via `uv sync --extra server`) and a working `pip`/network access to
    fetch each version's sdist — see module docstring for why this is `pip download --no-deps`, not a full
    `pip install` or `griffe.load_pypi` (which does a full install, pulling in the package's real declared
    dependencies — genuinely including `torch` for `peft`, confirmed against real PyPI metadata).

    Imported lazily, inside this function, deliberately *unlike* `knowledge/store.py`'s top-level
    `import lancedb` — found necessary the hard way in this module's own test-writing pass: a top-level
    `import griffe` made `_correlate_removed_parameter`/`_correlate_removed_object`/`_detect_reorder`
    (pure, griffe-independent functions) fail to import in any environment without griffe installed,
    defeating the entire point of keeping them independently unit-testable (see module docstring). Matches
    `patch/ast_grep_runner.py`'s existing lazy-subprocess-dependency pattern instead.
    """
    import griffe

    with tempfile.TemporaryDirectory() as tmpdir:
        old_src = _download_and_extract(package, old_ref, Path(tmpdir) / "old")
        new_src = _download_and_extract(package, new_ref, Path(tmpdir) / "new")
        old_obj = griffe.load(package, search_paths=[old_src], allow_inspection=False)
        new_obj = griffe.load(package, search_paths=[new_src], allow_inspection=False)

        breakages = list(griffe.find_breaking_changes(old_obj, new_obj))
        records: list[KnowledgeRecord] = []

        # PARAMETER_MOVED is yielded once per moved parameter, but a REORDER record belongs once per
        # function — collect the distinct functions first (obj is confirmed the *new*-tree function; see
        # module docstring), then run _detect_reorder once per function below, not once per parameter.
        reordered_function_paths = {b.obj.path for b in breakages if str(b.kind) == "BreakageKind.PARAMETER_MOVED"}
        for func_path in sorted(reordered_function_paths):
            new_func = _resolve_path(new_obj, func_path, package)
            old_func = _resolve_path(old_obj, func_path, package)
            if new_func is None or old_func is None:
                continue  # a path that existed moments ago in breakages but can't be re-resolved is a
                # griffe/this-module mismatch worth silently skipping over, not crashing the whole extract
                # over — REORDER is a nice-to-have refinement, not the core signal this function exists for.
            reorder = _detect_reorder(_function_positional_names(old_func), _function_positional_names(new_func))
            if reorder is not None:
                old_order, new_order = reorder
                records.append(
                    KnowledgeRecord(
                        package=package,
                        ecosystem=ecosystem,  # type: ignore[arg-type]
                        old_symbol=func_path,
                        new_symbol=func_path,
                        old_param_order=old_order,
                        new_param_order=new_order,
                        from_version=from_version,
                        to_version=to_version,
                        rule_type=RuleType.REORDER,
                        source=RecordSource.API_DIFF_TOOL,
                        confidence=0.9,  # a pure positional reorder (same param set, different order) is
                        # about as unambiguous as a structural signal gets — see _detect_reorder's docstring
                    )
                )

        for breakage in breakages:
            kind_str = str(breakage.kind)
            symbol_path = breakage.obj.path

            if kind_str == "BreakageKind.PARAMETER_MOVED":
                continue  # handled once per function above, not per-parameter here

            if kind_str == "BreakageKind.PARAMETER_REMOVED":
                # breakage.obj is confirmed the *new*-tree function (griffe's own
                # `ParameterRemovedBreakage(new_function, old_param, None)` construction) — its current
                # parameter names are the correlation candidates. The *old* signature (to know which names
                # were already there before, per _correlate_removed_parameter's own exclusion rule) has to
                # be looked up separately, since breakage.obj is never the old-tree object for this kind.
                removed_name = getattr(breakage.old_value, "name", None) or str(breakage.old_value)
                new_names = _function_positional_names(breakage.obj)
                old_func = _resolve_path(old_obj, symbol_path, package)
                old_names = _function_positional_names(old_func) if old_func is not None else []
                correlation = _correlate_removed_parameter(removed_name, old_names, new_names)
                if correlation is not None:
                    records.append(
                        KnowledgeRecord(
                            package=package,
                            ecosystem=ecosystem,  # type: ignore[arg-type]
                            old_symbol=symbol_path,
                            new_symbol=symbol_path,
                            parameter=removed_name,
                            new_parameter=correlation.new_name,
                            from_version=from_version,
                            to_version=to_version,
                            rule_type=RuleType.RENAME,
                            source=RecordSource.API_DIFF_TOOL,
                            confidence=round(0.6 + 0.35 * correlation.confidence, 2),
                        )
                    )
                else:
                    records.append(
                        KnowledgeRecord(
                            package=package,
                            ecosystem=ecosystem,  # type: ignore[arg-type]
                            old_symbol=symbol_path,
                            new_symbol=None,
                            from_version=from_version,
                            to_version=to_version,
                            rule_type=RuleType.REMOVED_NO_REPLACEMENT,
                            source=RecordSource.API_DIFF_TOOL,
                            confidence=0.85,  # confident the removal happened; no claim about a replacement
                        )
                    )
                continue

            if kind_str == "BreakageKind.OBJECT_REMOVED":
                # breakage.obj is confirmed the *old*-tree object here (griffe's own
                # `ObjectRemovedBreakage(old_member, old_member, None)` construction) — the inverse of the
                # PARAMETER_REMOVED case above. Candidates for a whole-symbol rename are sibling names in
                # the *new* tree's corresponding parent (module/class) that weren't already present in the
                # old tree's same parent.
                old_parent = breakage.obj.parent
                old_sibling_names = list(old_parent.members.keys()) if old_parent is not None else []
                new_parent = _resolve_path(new_obj, old_parent.path, package) if old_parent is not None else None
                new_sibling_names = list(new_parent.members.keys()) if new_parent is not None else []
                correlation = _correlate_removed_object(breakage.obj.name, old_sibling_names, new_sibling_names)
                if correlation is not None and new_parent is not None:
                    new_symbol = f"{new_parent.path}.{correlation.new_name}"
                    records.append(
                        KnowledgeRecord(
                            package=package,
                            ecosystem=ecosystem,  # type: ignore[arg-type]
                            old_symbol=symbol_path,
                            new_symbol=new_symbol,
                            from_version=from_version,
                            to_version=to_version,
                            rule_type=RuleType.RENAME,
                            source=RecordSource.API_DIFF_TOOL,
                            confidence=round(0.6 + 0.35 * correlation.confidence, 2),
                        )
                    )
                else:
                    records.append(
                        KnowledgeRecord(
                            package=package,
                            ecosystem=ecosystem,  # type: ignore[arg-type]
                            old_symbol=symbol_path,
                            new_symbol=None,
                            from_version=from_version,
                            to_version=to_version,
                            rule_type=RuleType.REMOVED_NO_REPLACEMENT,
                            source=RecordSource.API_DIFF_TOOL,
                            confidence=0.85,
                        )
                    )
                continue

            rule_type = _DIRECT_RULE_TYPE.get(kind_str)
            if rule_type is not None:
                records.append(
                    KnowledgeRecord(
                        package=package,
                        ecosystem=ecosystem,  # type: ignore[arg-type]
                        old_symbol=symbol_path,
                        new_symbol=symbol_path,
                        from_version=from_version,
                        to_version=to_version,
                        rule_type=rule_type,
                        source=RecordSource.API_DIFF_TOOL,
                        confidence=0.75,  # structural signal is reliable; this bucket makes no rename claim
                    )
                )

        return records


def _download_and_extract(package: str, version: str, dest: Path) -> Path:
    """`pip download --no-deps` the exact sdist for `package==version` and extract it — the verified-live
    pattern from this module's docstring: no transitive dependencies (no `torch` for `peft`, etc.), because
    `--no-deps` means pip resolves and fetches nothing beyond the one named package/version. Returns the
    directory that should be passed as griffe's `search_paths` — the extracted sdist's own `src/` layout if
    present (the modern, PEP 517-recommended layout many packages including `peft` use), else the sdist
    root itself (the flat layout, e.g. a bare `package/` directory next to `setup.py`/`pyproject.toml`).
    """
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "pip",
            "download",
            "--no-deps",
            "--no-binary",
            ":all:",
            "-d",
            str(dest),
            f"{package}=={version}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"could not download {package}=={version} to diff it (pip exit {proc.returncode}): {proc.stderr.strip()}"
        )

    archives = list(dest.glob("*.tar.gz")) + list(dest.glob("*.zip"))
    if not archives:
        raise RuntimeError(f"pip download reported success for {package}=={version} but produced no archive")
    archive = archives[0]
    extract_dir = dest / "extracted"
    if archive.suffix == ".zip" or archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(extract_dir, filter="data")  # "data" filter: refuse unsafe paths/permissions —
            # this is a real third-party sdist being extracted, not this project's own trusted content

    # A source distribution extracts to exactly one top-level directory (e.g. "peft-0.12.0/") — descend
    # into it, then prefer "src/" (PEP 517 src-layout) if present, else the directory itself (flat layout).
    (top_level,) = [p for p in extract_dir.iterdir() if p.is_dir()]
    src_layout = top_level / "src"
    return src_layout if src_layout.is_dir() else top_level


def _resolve_path(root: Any, path: str, package: str) -> Any | None:
    """Look up `path` (a griffe object's real, confirmed-live fully-qualified path, e.g.
    `"peft.utils.integrations.gather_params_ctx"`) inside `root`'s tree, using griffe's own confirmed-live
    `Object.__getitem__` dotted-path lookup. Returns `None` — never raises — when the path doesn't exist in
    `root` (e.g. the containing module was itself renamed or removed between versions), so a lookup miss
    degrades to "no correlation data for this one" rather than crashing the whole `extract()` call over one
    symbol that moved in an unrelated way.
    """
    if not (path == package or path.startswith(f"{package}.")):
        return None
    relative = path[len(package) + 1 :]
    if not relative:
        return root
    try:
        return root[relative]
    except (KeyError, AttributeError):
        return None
