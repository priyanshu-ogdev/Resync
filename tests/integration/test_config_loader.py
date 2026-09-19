"""Real tests for resync.toml loading and writing — a genuine coverage gap found in review: this file, the
project's own "compatibility contract" per docs/architecture.md, had zero dedicated tests despite being
referenced throughout the documentation as load-bearing.
"""

import datetime
import pathlib

from resync.config.loader import load, persist_policy
from resync.config.schema import Policy


def test_load_with_no_file_returns_defaults(tmp_path: pathlib.Path) -> None:
    """A missing resync.toml is not an error — a project with none simply gets default behavior."""
    config = load(tmp_path)
    assert config.project.mode == "hybrid"
    assert config.pin == []
    assert config.exception == []
    assert config.policy == []


def test_load_the_projects_own_resync_toml() -> None:
    """The project dogfoods its own format — load it for real rather than only checking it parses as TOML."""
    repo_root = pathlib.Path(__file__).parent.parent.parent
    config = load(repo_root)
    assert config.project.mode == "hybrid"
    assert any(p.package == "torch" for p in config.pin)
    assert any(e.path == "src/legacy/adapter.py::old_lora_merge" for e in config.exception)
    assert any(p.symbol == "peft.PeftModel.from_pretrained" for p in config.policy)


def test_is_pinned_or_frozen_matches_a_real_pin() -> None:
    repo_root = pathlib.Path(__file__).parent.parent.parent
    config = load(repo_root)
    assert config.is_pinned_or_frozen("torch") is True
    assert config.is_pinned_or_frozen("some_unrelated_package") is False


def test_policy_for_finds_a_matching_persisted_decision() -> None:
    repo_root = pathlib.Path(__file__).parent.parent.parent
    config = load(repo_root)
    policy = config.policy_for("peft.PeftModel.from_pretrained", "param_split")
    assert policy is not None
    assert policy.decision == "shift"


def test_policy_for_returns_none_when_no_match() -> None:
    repo_root = pathlib.Path(__file__).parent.parent.parent
    config = load(repo_root)
    assert config.policy_for("nonexistent.symbol", "rename") is None


def test_persist_policy_round_trips(tmp_path: pathlib.Path) -> None:
    persist_policy(
        tmp_path,
        Policy(
            symbol="pkg.func",
            change_type="rename",
            decision="sync",
            confirmed_by="test",
            last_confirmed=datetime.date(2026, 1, 1),
        ),
    )
    reloaded = load(tmp_path)
    assert len(reloaded.policy) == 1
    assert reloaded.policy[0].symbol == "pkg.func"
    assert reloaded.policy[0].decision == "sync"


def test_persist_policy_appends_without_dropping_existing_data(tmp_path: pathlib.Path) -> None:
    """Regression-shaped test: persist_policy must not silently overwrite pins/exceptions already in the
    file when it writes a new policy."""
    (tmp_path / "resync.toml").write_text('[[pin]]\npackage = "torch"\nmax_version = "2.1.0"\nreason = "test"\n')
    persist_policy(
        tmp_path,
        Policy(
            symbol="pkg.func",
            change_type="rename",
            decision="sync",
            confirmed_by="test",
            last_confirmed=datetime.date(2026, 1, 1),
        ),
    )
    reloaded = load(tmp_path)
    assert len(reloaded.pin) == 1, "the existing pin must survive persist_policy writing a new policy"
    assert reloaded.pin[0].package == "torch"
    assert len(reloaded.policy) == 1
