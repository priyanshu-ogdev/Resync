"""Wraps the ast-grep CLI binary via subprocess — deliberately not the ast-grep-py bindings, whose fix/rewrite
support was described upstream as experimental at review time, unlike the CLI's --rewrite/--update-all flags,
which are stable, documented, and used here exactly as documented (docs/tech-stack.md's binding-version-
mismatch reasoning).

Only handles the two mechanical RuleTypes (RENAME, REORDER) — see patch/taxonomy.py for the strategy
decision and docs/architecture.md's signature-change taxonomy for why SPLIT/MERGE/etc. are not mechanical.

Findings from actually running the real binary against real fixtures, kept documented here because each
failure mode is easy to reintroduce if this file is "cleaned up" without re-running the fixture tests:

1. `ast-grep run`/`scan` follow grep's own exit-code convention: 0 means matches were found, 1 means the run
   succeeded but found nothing, and only other codes indicate an actual failure.
2. `--json` and `-U`/`--update-all` do not compose on either `run` or `scan` — confirmed both empirically
   (diffing a file before/after running both flags together) and in `ast-grep scan --help`'s own text, which
   states outright that `--update-all` "conflicts with... --json". Every code path below runs a read-only
   `--json` pass and a separate, `--json`-free `-U` pass, never both in one invocation.
3. A whole-symbol rename needs two rules, not one: renaming call sites does nothing to the
   `from pkg import old_name` line that made the old name available. Both a call-site rule and an
   import-statement rule are applied for this case.

Review upgrade, replacing the first version's approach: parameter-level renames (e.g. use_auth_token ->
token) were originally matched by wrapping the pattern in a fake placeholder call plus `--selector
keyword_argument` — a working but hacky pattern-parsing workaround. ast-grep's own documentation shows a
cleaner, idiomatic way to express exactly this: a YAML rule with `kind: keyword_argument` and field-scoped
`has` sub-rules constraining the argument's name to an exact literal match. This is used via `ast-grep scan
--rule <tempfile>` instead of `ast-grep run -p ... --selector ...`, confirmed working for both preview and
apply against the same real fixture the placeholder version was tested against.

REORDER support (genuinely unimplemented before this pass, despite being listed as mechanical in the
taxonomy) is now real: KnowledgeRecord.old_param_order/new_param_order supply position labels, and this
module captures each old position into its own metavariable, then re-emits them in the new order — confirmed
against a real fixture that ast-grep supports exactly this reorder-by-metavariable-reuse pattern, including a
trailing `$$$REST` catch-all so arguments outside the reordered positions (e.g. an unrelated trailing keyword
argument) are preserved untouched rather than silently dropped from the match.

**Important, load-bearing limitation found during that same verification, and not papered over**: unlike
RENAME, a REORDER fix is not naturally idempotent. RENAME becomes a permanent no-op once applied, because the
old name genuinely stops existing in the code for the pattern to match again. A positional swap has no such
property — `connect($P0, $P1, $$$REST)` matches `connect(host, port, ...)` and, just as validly, matches the
already-fixed `connect(port, host, ...)`, since the pattern only sees "two arbitrary expressions in some
order," not which one is semantically host vs. port. Applying a REORDER fix a second time swaps it right
back. This is proven, not assumed, by `tests/integration/test_ast_grep_runner.py`'s dedicated
non-idempotency test — a red-flag test asserting the oscillation happens, kept deliberately failing-if-fixed
so nobody "fixes" it by loosening the assertion without solving the actual problem.

**This guard is now built.** `apply()` accepts an optional `repo_root` — when given, it loads `resync.toml`
(`config/loader.py`), checks `ResyncConfig.already_applied(file, symbol, change_type, fingerprint)` before
running any REORDER step, skips (returning `[]`, touching nothing) if the identical transition was already
recorded as applied to this file, and otherwise applies and persists a new `AppliedFix` record
(`config/schema.py`) afterward via `config/loader.persist_applied_fix`. The fingerprint is derived from the
specific old/new positional order (`_reorder_fingerprint`), not just the symbol, so a genuinely new reorder
of the same symbol in some future package version is still applied rather than wrongly skipped. The pattern
itself is still not idempotent at the ast-grep level — that underlying fact doesn't change and isn't meant
to — but the caller-visible behavior at the `apply()` layer now is, which is the property the scheduled sweep
actually needs. Without `repo_root` (e.g. a one-off interactive `resync fix` invocation, or in tests that
don't care about the ledger), `apply()` behaves exactly as before: no ledger check, no persistence.

**A third review pass found a genuinely dangerous bug, not just a missed case**: the original whole-symbol
import fix used a plain `from $MOD import {old_name}` -> `from $MOD import {new_name}` pattern/rewrite pair.
Against `from pkg import old_name`, this worked. Against the very common `from pkg import old_name,
other_thing`, it matched the *entire* import statement and silently dropped `other_thing` on rewrite —
confirmed by running it against exactly that case and reading the corrupted output, not by reasoning about
it abstractly. The fix targets only the specific imported identifier via a YAML rule with a nested `inside`
chain (`kind: identifier` inside a `dotted_name` inside an `import_from_statement`), which matches and
replaces just that one name, leaving commas and sibling names outside the matched span entirely. Regression
test: `test_whole_symbol_rename_preserves_other_names_on_a_multi_name_import_line`.

Also fixed in this pass, smaller but worth noting: the YAML rules' `language:` field used plain
`str.capitalize()`, which happens to produce the right string for "python" -> "Python" but would silently
produce the wrong one for multi-word language names ("javascript" -> "Javascript" instead of ast-grep's
expected "JavaScript"). Not yet triggered since Phase 2 is Python-only in scope, but left uncorrected it
would have been a landmine for Phase 5's TypeScript/Rust adapters. Replaced with an explicit mapping
(`_LANGUAGE_NAMES`) that should be extended and verified against a real ast-grep run for each new language
added, not assumed correct by pattern.

**A fourth pass, this time designing a safety feature rather than fixing a bug — finding 10.** Every pattern
above matches by *name*: a function name, a keyword-argument name. None of them verify that the matched call
actually originates from the tracked package. Confirmed with a real fixture: a file containing an unrelated
local `def old_helper` with no import of the tracked package at all produced a match purely by namesake
coincidence — and in a second fixture, a file that *does* import the package but also shadows the same name
with a local definition produced a match for a call that Python's own scoping resolves to the local
function, not the import. `_package_is_imported` now gates every mechanical patch on the target file actually
containing an `import package` or `from package import ...` statement first. This closes the first case
completely (proven by `test_import_guard_skips_a_file_that_never_imports_the_package`) but not the second —
shadowing within a file that legitimately imports the package requires real scope resolution this syntactic
tool doesn't do, and that residual risk is documented and tested as a known limitation
(`test_import_guard_does_not_catch_local_shadowing_this_is_a_known_residual_risk`), not silently left
unaddressed. The differential-equivalence layer (Phase 3) is the intended backstop for that residual case,
since a wrong rename under shadowing would produce an observable behavioral divergence that layer exists to
catch.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from resync.config import loader as config_loader
from resync.config.schema import AppliedFix
from resync.knowledge.schema import KnowledgeRecord, RuleType

# ast-grep's YAML `language:` field expects specific capitalization that plain str.capitalize() gets wrong
# for multi-word language names — "javascript".capitalize() produces "Javascript", not the "JavaScript"
# ast-grep actually expects. Phase 2 is Python-only in scope, where capitalize() happens to be correct by
# coincidence, but leaving that as the only logic would be a landmine for Phase 5's TypeScript/Rust adapters.
# This mapping should be extended (and each new entry verified against a real ast-grep run, not assumed) as
# more languages are added — see docs/multi-language-adapters.md.
_LANGUAGE_NAMES = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "tsx": "Tsx",
    "rust": "Rust",
    "go": "Go",
}


def _ast_grep_language_name(language: str) -> str:
    return _LANGUAGE_NAMES.get(language.lower(), language.capitalize())


# Resolve the ast-grep binary path once at module load, so every subprocess call uses a concrete path
# rather than relying purely on the caller's PATH at runtime. The canonical install for this project
# is `pip install ast-grep-cli` (AGENTS.md), which places the binary alongside the running Python
# interpreter in the venv's bin/ directory — but callers don't always activate the venv first
# (CI, devcontainers, and IDE-spawned subprocesses all regularly have a sys.executable inside a venv
# while PATH points elsewhere). Resolution order:
#   1. `shutil.which("ast-grep")` — respects the caller's PATH (works when venv is activated or when
#      ast-grep is installed globally, e.g. via Homebrew or cargo install).
#   2. The bin/ directory of the running Python interpreter — the venv-sibling location that
#      `pip install ast-grep-cli` always uses, regardless of whether the venv is "activated".
# Falling back to the bare string "ast-grep" as a last resort preserves the old behavior for any
# exotic install layout not covered above, while making sure the common cases work without activation.
_AST_GREP_BINARY: str = (
    shutil.which("ast-grep")
    or str(Path(sys.executable).parent / "ast-grep")
    or "ast-grep"  # last-resort fallback — will raise FileNotFoundError at subprocess.run time
)


class AstGrepError(RuntimeError):
    """Raised only for genuine ast-grep failures (missing binary, invalid pattern) — never for "zero
    matches", which is exit code 1 and a legitimate, common outcome, not an error."""


def _run_subprocess(cmd: list[str]) -> str:
    # Replace the bare "ast-grep" sentinel at position 0 with the resolved binary path so every
    # call goes through the same resolution logic above, not a bare PATH lookup.
    resolved_cmd = [_AST_GREP_BINARY if c == "ast-grep" else c for c in cmd]
    result = subprocess.run(resolved_cmd, capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise AstGrepError(f"ast-grep failed (exit {result.returncode}): {result.stderr}")
    return result.stdout


def _keyword_argument_rule_yaml(parameter: str, new_parameter: str, language: str) -> str:
    """The idiomatic YAML-rule replacement for the placeholder-wrapper hack — see module docstring."""
    rule = {
        "id": f"resync-rename-{parameter}",
        "language": _ast_grep_language_name(language),
        "rule": {
            "kind": "keyword_argument",
            "all": [
                {"has": {"field": "name", "pattern": parameter}},
                {"has": {"field": "value", "pattern": "$VAL"}},
            ],
        },
        "fix": f"{new_parameter}=$VAL",
    }
    return yaml.safe_dump(rule)


def _import_name_rule_yaml(old_name: str, new_name: str, language: str) -> str:
    """Targets only the specific imported identifier inside a `from $MOD import ...` statement, not the
    whole statement.

    Real bug this replaces: `from $MOD import {old_name}` / `from $MOD import {new_name}` as a plain
    pattern/rewrite pair matches the *entire* import line, including every other comma-separated name on it
    — so `from pkg import old_name, other_thing` silently lost `other_thing` on rewrite. Confirmed by testing
    against exactly that case. The fix, confirmed the same way: target the innermost `identifier` node,
    scoped via nested `inside` to only the ones that are part of a `dotted_name` that is itself part of an
    `import_from_statement` — this matches and replaces just that one name, leaving commas and sibling names
    untouched since they're outside the matched span entirely.
    """
    rule = {
        "id": f"resync-rename-import-{old_name}",
        "language": _ast_grep_language_name(language),
        "rule": {
            "kind": "identifier",
            "pattern": old_name,
            "inside": {"kind": "dotted_name", "inside": {"kind": "import_from_statement"}},
        },
        "fix": new_name,
    }
    return yaml.safe_dump(rule)


def _reorder_pattern_and_rewrite(record: KnowledgeRecord) -> tuple[str, str]:
    """Capture each old positional argument into its own metavariable, then re-emit them in the new
    order — validated against a real ast-grep run, not assumed from the metavariable docs alone.

    A real bug caught during that verification, worth keeping documented: the first version only matched
    exactly len(old_param_order) arguments, so a call with any additional trailing argument (e.g. a keyword
    argument that isn't part of the reorder at all) matched nothing — confirmed by testing against a fixture
    with a trailing `timeout=30` kwarg. The trailing `$$$REST` multi-metavariable fixes this by capturing and
    re-emitting anything beyond the reordered positions unchanged, the same technique the whole-symbol-rename
    path already uses via `$$$ARGS`.
    """
    old_order = record.old_param_order
    new_order = record.new_param_order
    assert old_order and new_order  # enforced by KnowledgeRecord's own validator; see schema.py
    symbol_name = record.old_symbol.rsplit(".", 1)[-1]
    metavars = [f"P{i}" for i in range(len(old_order))]
    pattern = f"{symbol_name}(" + ", ".join(f"${m}" for m in metavars) + ", $$$REST)"
    label_to_metavar = dict(zip(old_order, metavars, strict=True))
    rewrite_positions = ", ".join(f"${label_to_metavar[label]}" for label in new_order)
    rewrite = f"{symbol_name}({rewrite_positions}, $$$REST)"
    return pattern, rewrite


def _reorder_fingerprint(record: KnowledgeRecord) -> str:
    """Stable fingerprint of a REORDER's specific transition (e.g. host/port -> port/host), not just the
    symbol — see AppliedFix's docstring in config/schema.py for why the distinction matters: a future
    package version reordering the same symbol's arguments *again* must produce a different fingerprint,
    so it's correctly treated as a new fix rather than silently skipped as already applied.
    """
    old_order = record.old_param_order or []
    new_order = record.new_param_order or []
    payload = "|".join([record.old_symbol, *old_order, "->", *new_order])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _plan(record: KnowledgeRecord, language: str) -> list[dict[str, Any]]:
    """Returns a list of subprocess "steps": each is either a simple {pattern, rewrite} pair (run via
    `ast-grep run -p/-r`) or a {rule_yaml} step (run via `ast-grep scan --rule <tempfile>`)."""
    if record.parameter and record.new_parameter:
        return [{"rule_yaml": _keyword_argument_rule_yaml(record.parameter, record.new_parameter, language)}]

    if record.rule_type == RuleType.REORDER:
        pattern, rewrite = _reorder_pattern_and_rewrite(record)
        return [{"pattern": pattern, "rewrite": rewrite}]

    # Whole-symbol rename: call sites, plus the import statement that brought the old name into scope.
    old_name = record.old_symbol.rsplit(".", 1)[-1]
    new_name = (record.new_symbol or "").rsplit(".", 1)[-1]
    if not new_name:
        raise AstGrepError(f"Cannot generate a mechanical rewrite with no new_symbol: {record}")
    return [
        {"pattern": f"{old_name}($$$ARGS)", "rewrite": f"{new_name}($$$ARGS)"},
        {"rule_yaml": _import_name_rule_yaml(old_name, new_name, language)},
    ]


def _run_step(step: dict[str, Any], target_path: Path, language: str, write: bool) -> list[dict[str, Any]]:
    if "rule_yaml" in step:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(step["rule_yaml"])
            rule_path = f.name
        try:
            cmd = ["ast-grep", "scan", "--rule", rule_path]
            cmd.append("-U" if write else "--json")
            cmd.append(str(target_path))
            stdout = _run_subprocess(cmd)
        finally:
            Path(rule_path).unlink(missing_ok=True)
    else:
        cmd = ["ast-grep", "run", "-p", step["pattern"], "-r", step["rewrite"], "-l", language]
        cmd.append("-U" if write else "--json")
        cmd.append(str(target_path))
        stdout = _run_subprocess(cmd)

    if write:
        return []  # the write pass emits no JSON; preview() already captured what changed
    return json.loads(stdout) if stdout.strip() else []


def _package_is_imported(target_path: Path, package: str, language: str) -> bool:
    """Safety pre-check: does the target file even import the record's package?

    Real risk this addresses (finding 10, see module docstring): every mechanical pattern here matches by
    *name* — a function name, a keyword-argument name — not by verified origin. A file that happens to
    define or call something with the same name, but has nothing to do with the package being tracked, would
    otherwise be a false-positive match. Confirmed with a real fixture: a file containing an unrelated local
    `def old_helper` shadowing an import of the same name produced a match for a call that Python's own
    scoping rules resolve to the *local* function, not the imported one — renaming it would have been wrong.

    This check is a partial mitigation, not a complete one. It correctly filters out the common case (a file
    that doesn't touch the package at all), but it cannot detect the harder residual case above — a file
    that legitimately imports the package *and* separately shadows the same name locally. That residual risk
    is real and left as a known limitation; the differential-equivalence layer (Phase 3,
    docs/adr/0002-differential-equivalence-verification.md) is the intended backstop for it, since a wrong
    rename in a shadowing scenario would produce a `NameError` or behavioral divergence that layer is built
    to catch, even though this syntactic layer cannot.
    """
    for query in (f"import {package}", f"from {package} import $$$X"):
        cmd = ["ast-grep", "run", "-p", query, "-l", language, "--json", str(target_path)]
        stdout = _run_subprocess(cmd)
        if json.loads(stdout) if stdout.strip() else []:
            return True
    return False


def preview(record: KnowledgeRecord, target_path: Path, language: str = "python") -> list[dict[str, Any]]:
    """Dry run across every step for this record — returns the combined JSON match objects without writing
    anything. Always call this before apply(): the caller (Phase 3's verification layer) needs the preview
    to decide whether zero matches means "nothing to fix" or "the pattern didn't match what we expected".

    Gated by _package_is_imported before running any pattern — see that function's docstring for the
    false-positive risk this closes (partially) and the residual risk it doesn't.
    """
    if record.rule_type not in (RuleType.RENAME, RuleType.REORDER):
        raise AstGrepError(f"ast_grep_runner only handles mechanical rule types, got {record.rule_type}")
    if not _package_is_imported(target_path, record.package, language):
        return []
    matches: list[dict[str, Any]] = []
    for step in _plan(record, language):
        matches.extend(_run_step(step, target_path, language, write=False))
    return matches


def apply(
    record: KnowledgeRecord,
    target_path: Path,
    language: str = "python",
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Actually writes every step's rewrite to disk, in order. Callers should run this inside the sandboxed
    execution environment (docs/architecture.md#deployment-model, sandbox-runtime), never directly against a
    live checkout.

    `repo_root`, when given, activates the applied-already guard for REORDER (module docstring, finding 7):
    before touching the file, this checks `resync.toml`'s persisted `AppliedFix` ledger
    (config/schema.py/config/loader.py) for the exact same (file, symbol, transition) and skips — returning
    `[]`, writing nothing — if it's already there. After a successful REORDER apply, a new `AppliedFix` is
    persisted so the next scheduled pass sees it. RENAME and one-off calls with `repo_root=None` are
    unaffected: RENAME doesn't need the guard (see module docstring), and omitting `repo_root` preserves the
    original, ledger-free behavior for interactive/test use.
    """
    if record.rule_type not in (RuleType.RENAME, RuleType.REORDER):
        raise AstGrepError(f"ast_grep_runner only handles mechanical rule types, got {record.rule_type}")

    file_key = str(target_path.relative_to(repo_root)) if repo_root is not None else str(target_path)
    config = config_loader.load(repo_root) if repo_root is not None else None

    if record.rule_type == RuleType.REORDER and config is not None:
        fingerprint = _reorder_fingerprint(record)
        if config.already_applied(file_key, record.old_symbol, record.rule_type.value, fingerprint):
            return []

    matches = preview(record, target_path, language)
    if not matches:
        return []
    for step in _plan(record, language):
        _run_step(step, target_path, language, write=True)

    if record.rule_type == RuleType.REORDER and repo_root is not None:
        config_loader.persist_applied_fix(
            repo_root,
            AppliedFix(
                file=file_key,
                symbol=record.old_symbol,
                change_type=record.rule_type.value,
                fingerprint=_reorder_fingerprint(record),
                applied_at=date.today(),
            ),
        )

    return matches
