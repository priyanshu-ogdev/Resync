"""Integration test for server/tools.py's check_symbol_exists, against a real LanceDB table (not mocked) —
consistent with this project's own standing rule (AGENTS.md) that store-layer code needs a real instance,
not just a mocked unit test, as evidence it works.

The embedding call is monkeypatched (same pattern as tests/unit/test_store.py) since a live call to download
`nomic-embed-text-v1.5` isn't reachable from this environment — an already-documented, unrelated gap
(knowledge/embeddings.py's module docstring), not something this test is trying to hide.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resync.knowledge import store
from resync.knowledge.seed_data import SEED_RECORDS
from resync.server.tools import VerificationOutcome, check_symbol_exists


def _fake_embed(text: str) -> list[float]:
    return [0.0] * store.EMBEDDING_DIM


@pytest.fixture
def seeded_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(store, "embed_document", _fake_embed)
    db_path = store.default_db_path(tmp_path)
    db_path.parent.mkdir(parents=True)
    table = store.get_or_create_table(store.connect(db_path))
    store.upsert(table, SEED_RECORDS)
    return tmp_path


def test_symbol_with_deprecated_parameter_at_post_change_pin_is_flagged(seeded_repo: Path) -> None:
    """transformers.TrainingArguments has 8 concurrent RENAME/MERGE records at >=5.0.0 in the seed set —
    all should surface, not just one arbitrarily picked."""
    result = check_symbol_exists("transformers.TrainingArguments", "5.0.1", seeded_repo)
    assert result.outcome == VerificationOutcome.SYMBOL_DEPRECATED
    assert "no_cuda" in result.detail and "use_cpu" in result.detail
    assert "per_gpu_train_batch_size" in result.detail  # confirms multiple records are listed, not just one


def test_same_symbol_at_pre_change_pin_is_ok(seeded_repo: Path) -> None:
    """The real point of the version-range check: the same symbol, same known-future change, but the repo's
    actual pinned version predates it — must not be flagged."""
    result = check_symbol_exists("transformers.TrainingArguments", "4.50.0", seeded_repo)
    assert result.outcome == VerificationOutcome.OK


def test_removed_no_replacement_symbol_reports_symbol_removed(seeded_repo: Path) -> None:
    result = check_symbol_exists("transformers.AutoModelWithLMHead", "5.0.1", seeded_repo)
    assert result.outcome == VerificationOutcome.SYMBOL_REMOVED
    assert result.suggested_replacement is None  # honest: no single correct replacement exists


def test_unknown_symbol_with_no_records_is_ok(seeded_repo: Path) -> None:
    result = check_symbol_exists("some.totally.Unknown.Thing", "1.0.0", seeded_repo)
    assert result.outcome == VerificationOutcome.OK
    assert "No known changes" in result.detail


def test_free_text_query_is_not_treated_as_a_symbol_lookup(seeded_repo: Path) -> None:
    """check_symbol_exists is documented as taking a fully-qualified symbol — a free-text string routed
    through router.route() must not silently attempt (and fail) an exact-match lookup."""
    result = check_symbol_exists("how do I load a pretrained model", "1.0.0", seeded_repo)
    assert result.outcome == VerificationOutcome.OK
    assert "does not look like" in result.detail


def test_pinned_symbol_short_circuits_before_touching_the_store(tmp_path: Path) -> None:
    """No .resync/knowledge.lancedb directory exists at all here — if this didn't short-circuit on the pin
    check first, it would crash trying to open a nonexistent database, not just return the wrong answer."""
    (tmp_path / "resync.toml").write_text(
        '[[exception]]\npath = "transformers.TrainingArguments"\nreason = "frozen legacy code"\nexpires = 2099-01-01\n'
    )
    result = check_symbol_exists("transformers.TrainingArguments", "5.0.1", tmp_path)
    assert result.outcome == VerificationOutcome.PINNED
