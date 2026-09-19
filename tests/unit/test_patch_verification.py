"""Unit tests for server/patch_verification.py's verify_patch_equivalence, against a real, seeded LanceDB
table (embedding calls monkeypatched — the same documented network gap as elsewhere in this project).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resync.knowledge import store
from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType
from resync.knowledge.seed_data import SEED_RECORDS
from resync.server.patch_verification import PatchVerificationOutcome, verify_patch_equivalence


@pytest.fixture
def seeded_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(store, "embed_document", lambda text: [0.0] * store.EMBEDDING_DIM)
    db_path = store.default_db_path(tmp_path)
    db_path.parent.mkdir(parents=True)
    table = store.get_or_create_table(store.connect(db_path))
    store.upsert(table, SEED_RECORDS)
    return tmp_path


def test_correct_agent_drafted_fix_is_likely_correct(seeded_repo: Path) -> None:
    result = verify_patch_equivalence(
        "transformers.TrainingArguments",
        "TrainingArguments(no_cuda=True)",
        "TrainingArguments(use_cpu=True)",
        "5.0.1",
        seeded_repo,
    )
    assert result.outcome == PatchVerificationOutcome.LIKELY_CORRECT


def test_wrong_fix_does_not_match(seeded_repo: Path) -> None:
    result = verify_patch_equivalence(
        "transformers.TrainingArguments",
        "TrainingArguments(no_cuda=True)",
        "TrainingArguments(something_unrelated=True)",
        "5.0.1",
        seeded_repo,
    )
    assert result.outcome == PatchVerificationOutcome.DOES_NOT_MATCH_KNOWN_CHANGE


def test_invalid_syntax_is_caught_without_touching_the_knowledge_store(seeded_repo: Path) -> None:
    result = verify_patch_equivalence("transformers.TrainingArguments", "x", "def broken(:", "5.0.1", seeded_repo)
    assert result.outcome == PatchVerificationOutcome.INVALID_SYNTAX


def test_unknown_symbol_reports_no_known_change(seeded_repo: Path) -> None:
    result = verify_patch_equivalence("some.totally.Unknown", "x", "y", "1.0.0", seeded_repo)
    assert result.outcome == PatchVerificationOutcome.NO_KNOWN_CHANGE


def test_removed_no_replacement_is_not_statically_checkable_not_falsely_approved(seeded_repo: Path) -> None:
    """A REMOVED_NO_REPLACEMENT record has no generic structural signature to check — must never be
    silently reported as LIKELY_CORRECT just because it happens to parse."""
    result = verify_patch_equivalence(
        "transformers.AutoModelWithLMHead",
        "AutoModelWithLMHead()",
        "AutoModelForCausalLM()",
        "5.0.1",
        seeded_repo,
    )
    assert result.outcome == PatchVerificationOutcome.NOT_STATICALLY_CHECKABLE


def test_reorder_is_not_statically_checkable() -> None:
    """REORDER genuinely can't be verified from identifier presence alone — both old and new source use
    the exact same identifiers, just reordered. Confirms this doesn't false-positive as LIKELY_CORRECT."""
    from resync.server.patch_verification import _check_record_reflected

    record = KnowledgeRecord(
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
        confidence=0.95,
    )
    assert _check_record_reflected(record, "connect(host, port)", "connect(port, host)") is None


def test_premise_sanity_check_catches_an_unrelated_old_source(seeded_repo: Path) -> None:
    """old_source that doesn't even mention the old parameter suggests the wrong file/call-site was
    handed over — the premise itself is questionable, and that's reflected in the result rather than
    silently ignored (module docstring's stated reasoning for why old_source is used at all)."""
    result = verify_patch_equivalence(
        "transformers.TrainingArguments",
        "TrainingArguments()",  # doesn't mention no_cuda at all
        "TrainingArguments(use_cpu=True)",
        "5.0.1",
        seeded_repo,
    )
    assert result.outcome == PatchVerificationOutcome.DOES_NOT_MATCH_KNOWN_CHANGE


def test_pinned_symbol_short_circuits_before_touching_the_store(tmp_path: Path) -> None:
    (tmp_path / "resync.toml").write_text(
        '[[exception]]\npath = "frozen.Thing"\nreason = "legacy"\nexpires = 2099-01-01\n'
    )
    result = verify_patch_equivalence("frozen.Thing", "x", "y", "1.0.0", tmp_path)
    assert result.outcome == PatchVerificationOutcome.PINNED


def test_whole_symbol_rename_case(seeded_repo: Path) -> None:
    result = verify_patch_equivalence(
        "transformers.AutoModelForVision2Seq",
        "model = AutoModelForVision2Seq.from_pretrained(name)",
        "model = AutoModelForImageTextToText.from_pretrained(name)",
        "5.0.1",
        seeded_repo,
    )
    assert result.outcome == PatchVerificationOutcome.LIKELY_CORRECT


def test_a_comment_or_string_literal_cannot_spoof_the_check(seeded_repo: Path) -> None:
    """Real AST inspection, not text search — the expected keyword appearing only inside a string literal
    or comment must not count as the fix actually being applied."""
    result = verify_patch_equivalence(
        "transformers.TrainingArguments",
        "TrainingArguments(no_cuda=True)",
        '# TODO: use_cpu should replace no_cuda\nTrainingArguments(no_cuda=True)\nmsg = "use_cpu"',
        "5.0.1",
        seeded_repo,
    )
    assert result.outcome == PatchVerificationOutcome.DOES_NOT_MATCH_KNOWN_CHANGE
