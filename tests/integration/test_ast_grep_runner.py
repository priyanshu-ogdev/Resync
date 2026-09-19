"""Integration tests: these run the real ast-grep binary against real fixture files, per
docs/testing-strategy.md's principle that mocking away the tools this project's central claim depends on
would defeat the point of testing at all.

Every one of the three findings documented in ast_grep_runner.py's module docstring was caught by exactly
this kind of test failing first — these are that debugging session turned into permanent regression coverage,
not tests written after the fact to match already-correct code.
"""

import shutil
from pathlib import Path

import pytest

from resync.config import loader as config_loader
from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType
from resync.knowledge.seed_data import SEED_RECORDS
from resync.patch import ast_grep_runner

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def transformers_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "sample.py"
    shutil.copy(FIXTURES / "transformers-param-rename" / "sample.py", target)
    return target


@pytest.fixture
def whole_symbol_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "sample.py"
    shutil.copy(FIXTURES / "whole-symbol-rename" / "sample.py", target)
    return target


def test_parameter_rename_preview_does_not_modify_the_file(transformers_fixture: Path) -> None:
    record = SEED_RECORDS[0]
    original = transformers_fixture.read_text()
    matches = ast_grep_runner.preview(record, transformers_fixture)
    assert len(matches) == 2
    assert transformers_fixture.read_text() == original


def test_parameter_rename_apply_renames_both_call_sites(transformers_fixture: Path) -> None:
    record = SEED_RECORDS[0]
    ast_grep_runner.apply(record, transformers_fixture)
    content = transformers_fixture.read_text()
    assert "use_auth_token" not in content
    assert content.count("token=hf_token") == 2


def test_parameter_rename_is_idempotent(transformers_fixture: Path) -> None:
    record = SEED_RECORDS[0]
    ast_grep_runner.apply(record, transformers_fixture)
    assert ast_grep_runner.preview(record, transformers_fixture) == []


def test_whole_symbol_rename_updates_both_call_site_and_import(whole_symbol_fixture: Path) -> None:
    record = KnowledgeRecord(
        package="somepkg",
        ecosystem="pypi",
        old_symbol="somepkg.old_helper",
        new_symbol="somepkg.new_helper",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.9,
    )
    ast_grep_runner.apply(record, whole_symbol_fixture)
    content = whole_symbol_fixture.read_text()
    assert "old_helper" not in content
    assert "from somepkg import new_helper" in content
    assert 'new_helper(1, 2, keyword="value")' in content


def test_removed_no_replacement_is_rejected_not_silently_mishandled() -> None:
    """ast_grep_runner must refuse REMOVED_NO_REPLACEMENT records rather than guess — that rule type has no
    safe mechanical fix by definition (docs/architecture.md's signature-change taxonomy) and belongs to
    PatchStrategy.ESCALATE, never here."""
    record = KnowledgeRecord(
        package="pkg",
        ecosystem="pypi",
        old_symbol="pkg.gone_func",
        new_symbol=None,
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.REMOVED_NO_REPLACEMENT,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.9,
    )
    with pytest.raises(ast_grep_runner.AstGrepError):
        ast_grep_runner.preview(record, Path("/nonexistent"))


@pytest.fixture
def reorder_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "sample.py"
    shutil.copy(FIXTURES / "reorder-args" / "sample.py", target)
    return target


def _reorder_record() -> KnowledgeRecord:
    return KnowledgeRecord(
        package="netlib",
        ecosystem="pypi",
        old_symbol="netlib.connect",
        new_symbol="netlib.connect",
        old_param_order=["host", "port"],
        new_param_order=["port", "host"],
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.REORDER,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.9,
    )


def test_reorder_swaps_positions_and_preserves_trailing_kwargs(reorder_fixture: Path) -> None:
    record = _reorder_record()
    matches = ast_grep_runner.preview(record, reorder_fixture)
    assert len(matches) == 1
    ast_grep_runner.apply(record, reorder_fixture)
    content = reorder_fixture.read_text()
    assert "connect(port, host, timeout=30)" in content


def test_reorder_pattern_itself_is_still_not_idempotent_without_a_repo_root(
    reorder_fixture: Path,
) -> None:
    """The underlying ast-grep pattern is still not naturally idempotent (finding 7) — a positional swap
    matches its own already-fixed output just as validly as the original. This is deliberately still true
    and deliberately still tested: the fix for it lives one layer up, in the applied-already guard
    (test_reorder_apply_with_repo_root_is_safe_to_run_unattended_twice below), which is only active when a
    caller passes `repo_root`. Calling apply() without `repo_root` — a one-off interactive fix, or this test
    — intentionally gets the original, ledger-free behavior, so the oscillation is still observable here.
    """
    record = _reorder_record()
    ast_grep_runner.apply(record, reorder_fixture)
    assert "connect(port, host, timeout=30)" in reorder_fixture.read_text()

    # Running the exact same fix again with no repo_root is a no-op only if REORDER were truly idempotent
    # at the pattern level. It isn't: the pattern matches the now-swapped call just as validly and swaps it
    # right back. This is the behavior the guard test below exists to prevent when repo_root IS passed.
    second_pass_matches = ast_grep_runner.preview(record, reorder_fixture)
    assert len(second_pass_matches) == 1


def test_reorder_apply_with_repo_root_is_safe_to_run_unattended_twice(
    tmp_path: Path, reorder_fixture: Path
) -> None:
    """The applied-already guard: calling apply() twice with the same repo_root and the same record must
    swap once and then do nothing on the second call, instead of oscillating back and forth — this is the
    property an unattended scheduled sweep actually needs (see taxonomy.py and ast_grep_runner.py's module
    docstring).
    """
    repo_root = tmp_path
    target = repo_root / "sample.py"
    target.write_text(reorder_fixture.read_text())
    record = _reorder_record()

    first_pass = ast_grep_runner.apply(record, target, repo_root=repo_root)
    assert len(first_pass) == 1
    assert "connect(port, host, timeout=30)" in target.read_text()

    # A second, identical scheduled pass must be a true no-op: no matches returned, file untouched.
    second_pass = ast_grep_runner.apply(record, target, repo_root=repo_root)
    assert second_pass == []
    assert "connect(port, host, timeout=30)" in target.read_text()

    config = config_loader.load(repo_root)
    assert len(config.applied) == 1
    assert config.applied[0].symbol == record.old_symbol
    assert config.applied[0].file == "sample.py"


def test_reorder_apply_with_repo_root_still_applies_a_genuinely_different_reorder(
    tmp_path: Path, reorder_fixture: Path
) -> None:
    """The guard must not over-block: a *different* reorder transition for the same symbol (e.g. a later
    package version reordering the same call's arguments again) has a different fingerprint and must still
    be applied — see AppliedFix's docstring in config/schema.py.
    """
    repo_root = tmp_path
    target = repo_root / "sample.py"
    target.write_text(reorder_fixture.read_text())

    first_record = _reorder_record()
    ast_grep_runner.apply(first_record, target, repo_root=repo_root)
    assert "connect(port, host, timeout=30)" in target.read_text()

    different_record = KnowledgeRecord(
        package="netlib",
        ecosystem="pypi",
        old_symbol="netlib.connect",
        new_symbol="netlib.connect",
        old_param_order=["port", "host"],
        new_param_order=["host", "port"],
        from_version="2.0",
        to_version="3.0",
        rule_type=RuleType.REORDER,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.9,
    )
    second_pass = ast_grep_runner.apply(different_record, target, repo_root=repo_root)
    assert len(second_pass) == 1
    assert "connect(host, port, timeout=30)" in target.read_text()

    config = config_loader.load(repo_root)
    assert len(config.applied) == 2


def test_whole_symbol_rename_preserves_other_names_on_a_multi_name_import_line(
    tmp_path: Path,
) -> None:
    """Regression test for a real, dangerous bug: the original import-rename pattern matched and rewrote
    the entire `from pkg import a, b` statement, silently deleting every name on the line except the one
    being renamed. Confirmed against this exact fixture before and after the fix."""
    target = tmp_path / "sample.py"
    shutil.copy(FIXTURES / "multi-name-import-rename" / "sample.py", target)
    record = KnowledgeRecord(
        package="somepkg",
        ecosystem="pypi",
        old_symbol="somepkg.old_helper",
        new_symbol="somepkg.new_helper",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.9,
    )
    ast_grep_runner.apply(record, target)
    content = target.read_text()
    assert "from somepkg import new_helper, other_thing" in content, (
        f"other_thing must survive the rename — got: {content!r}"
    )
    assert 'new_helper(1, 2, keyword="value")' in content


def _rename_record() -> KnowledgeRecord:
    return KnowledgeRecord(
        package="somepkg",
        ecosystem="pypi",
        old_symbol="somepkg.old_helper",
        new_symbol="somepkg.new_helper",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.9,
    )


def test_import_guard_skips_a_file_that_never_imports_the_package(tmp_path: Path) -> None:
    """The common, correctly-handled case: a namesake with no relationship to the tracked package at all
    must never be touched."""
    target = tmp_path / "unrelated_file.py"
    shutil.copy(FIXTURES / "namesake-collision" / "unrelated_file.py", target)
    assert ast_grep_runner.preview(_rename_record(), target) == []
    ast_grep_runner.apply(_rename_record(), target)
    assert target.read_text() == (FIXTURES / "namesake-collision" / "unrelated_file.py").read_text()


def test_import_guard_does_not_catch_local_shadowing_this_is_a_known_residual_risk(
    tmp_path: Path,
) -> None:
    """This test intentionally documents a real limitation rather than hiding it: a file that legitimately
    imports the package, but separately shadows the same name with a local definition, still produces a
    match — and applying it would incorrectly rename a call that Python's own scoping resolves to the local
    function, not the import. See ast_grep_runner.py's module docstring, finding 10, for why this is left as
    a known gap for the differential-equivalence layer (Phase 3) to catch downstream, rather than solved
    here with real import-scope resolution, which this syntactic tool does not do.

    Do not "fix" this test by asserting zero matches; that would misrepresent what the import-guard actually
    checks (presence of an import, not resolved reference identity) as more than it is.
    """
    target = tmp_path / "shadowed_file.py"
    shutil.copy(FIXTURES / "namesake-collision" / "shadowed_file.py", target)
    matches = ast_grep_runner.preview(_rename_record(), target)
    assert len(matches) >= 1, (
        "If this assertion starts failing, real import-scope resolution has been added and this test "
        "(and the corresponding limitation note in ast_grep_runner.py) should be updated to reflect that."
    )
