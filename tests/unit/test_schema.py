"""Tests for KnowledgeRecord's constructor-time validation — added after a review found that a RENAME
record with no actual target (no changed new_symbol, no parameter/new_parameter pair) could be constructed
silently, with the breakage only surfacing several layers downstream inside ast_grep_runner.py. See
schema.py's docstring."""

from datetime import date

import pytest
from pydantic import ValidationError

from resync.config.schema import AppliedFix, ResyncConfig
from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType


def _base_kwargs(**overrides):
    kwargs = dict(
        package="pkg",
        ecosystem="pypi",
        old_symbol="pkg.func",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.API_DIFF_TOOL,
        confidence=0.9,
    )
    kwargs.update(overrides)
    return kwargs


def test_rename_with_no_target_is_rejected() -> None:
    with pytest.raises(ValidationError):
        KnowledgeRecord(**_base_kwargs(new_symbol="pkg.func"))  # same as old_symbol, no parameter either


def test_rename_with_changed_symbol_is_accepted() -> None:
    KnowledgeRecord(**_base_kwargs(new_symbol="pkg.func2"))


def test_rename_with_parameter_pair_is_accepted() -> None:
    KnowledgeRecord(**_base_kwargs(new_symbol="pkg.func", parameter="old_kw", new_parameter="new_kw"))


def test_removed_no_replacement_with_new_symbol_set_is_rejected() -> None:
    with pytest.raises(ValidationError):
        KnowledgeRecord(**_base_kwargs(rule_type=RuleType.REMOVED_NO_REPLACEMENT, new_symbol="pkg.func2"))


def test_removed_no_replacement_with_new_symbol_none_is_accepted() -> None:
    KnowledgeRecord(**_base_kwargs(rule_type=RuleType.REMOVED_NO_REPLACEMENT, new_symbol=None))


def test_reorder_requires_both_orders() -> None:
    with pytest.raises(ValidationError):
        KnowledgeRecord(**_base_kwargs(rule_type=RuleType.REORDER, new_symbol="pkg.func"))


def test_reorder_requires_equal_length_orders() -> None:
    with pytest.raises(ValidationError):
        KnowledgeRecord(
            **_base_kwargs(
                rule_type=RuleType.REORDER,
                new_symbol="pkg.func",
                old_param_order=["a", "b"],
                new_param_order=["a", "b", "c"],
            )
        )


def test_reorder_requires_a_true_permutation() -> None:
    with pytest.raises(ValidationError):
        KnowledgeRecord(
            **_base_kwargs(
                rule_type=RuleType.REORDER,
                new_symbol="pkg.func",
                old_param_order=["a", "b"],
                new_param_order=["a", "c"],  # "c" isn't in old_param_order at all
            )
        )


def test_reorder_with_valid_permutation_is_accepted() -> None:
    KnowledgeRecord(
        **_base_kwargs(
            rule_type=RuleType.REORDER,
            new_symbol="pkg.func",
            old_param_order=["a", "b"],
            new_param_order=["b", "a"],
        )
    )


def test_already_applied_normalizes_path_separators_across_os() -> None:
    config = ResyncConfig(
        applied=[
            AppliedFix(
                file="src/resync/patch/ast_grep_runner.py",
                symbol="pkg.func",
                change_type="reorder",
                fingerprint="abc12345",
                applied_at=date.today(),
            )
        ]
    )
    # Query with Windows backslashes matches POSIX stored path
    assert config.already_applied(
        "src\\resync\\patch\\ast_grep_runner.py",
        "pkg.func",
        "reorder",
        "abc12345",
    )
    # Stored with Windows backslashes matches POSIX query
    config_win = ResyncConfig(
        applied=[
            AppliedFix(
                file="src\\resync\\patch\\ast_grep_runner.py",
                symbol="pkg.func",
                change_type="reorder",
                fingerprint="abc12345",
                applied_at=date.today(),
            )
        ]
    )
    assert config_win.already_applied(
        "src/resync/patch/ast_grep_runner.py",
        "pkg.func",
        "reorder",
        "abc12345",
    )
