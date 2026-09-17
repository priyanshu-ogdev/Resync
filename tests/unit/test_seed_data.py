"""Per docs/knowledge/seed_data.py's own docstring: this seed set must stay small and verified. This test
enforces that discipline structurally rather than trusting a code comment alone — a future contributor
adding unverified bulk records would fail this test unless they also update it, which is a deliberate,
small piece of friction."""

from resync.knowledge.schema import RuleType
from resync.knowledge.seed_data import SEED_RECORDS


def test_seed_set_is_small_and_intentional() -> None:
    # A generous ceiling, not a target — see the module docstring on why this project doesn't bulk-generate
    # "known" changes. Raise this only alongside real, cited verification for each new record.
    assert len(SEED_RECORDS) <= 20


def test_every_seed_record_has_high_confidence() -> None:
    # Every record here is claimed as independently verified; a low-confidence "seed" record would be a
    # contradiction in terms.
    assert all(record.confidence >= 0.9 for record in SEED_RECORDS)


def test_seed_records_cover_the_flagship_packages() -> None:
    packages = {record.package for record in SEED_RECORDS}
    assert packages <= {"transformers", "peft", "bitsandbytes", "torch"}


def test_rename_records_have_both_symbols_populated() -> None:
    for record in SEED_RECORDS:
        if record.rule_type == RuleType.RENAME:
            assert record.new_symbol is not None


def test_parameter_level_renames_keep_the_symbol_clean() -> None:
    """Regression test for the real bug this seed set originally shipped with: old_symbol/new_symbol must
    stay a clean, fully-qualified symbol path — never a call signature with placeholder arguments — with the
    specific change captured in parameter/new_parameter instead. A record failing this would silently break
    both exact-symbol lookup and router.py's fully-qualified-symbol regex, exactly as the original version
    did."""
    for record in SEED_RECORDS:
        if record.parameter is not None:
            assert "(" not in record.old_symbol
            assert ")" not in record.old_symbol
            assert "=" not in record.old_symbol
            assert record.new_parameter is not None


def test_seed_function_actually_upserts_the_seed_records(monkeypatch) -> None:
    """The properties above test SEED_RECORDS as data; this tests that seed() itself, as a function, does
    what its name claims — a gap in the previous pass, where every other test checked the data but nothing
    exercised the function that's actually called at startup."""
    from resync.knowledge import seed_data, store

    monkeypatch.setattr(store, "embed_document", lambda text: [0.0] * 768)
    upserted: list = []

    class FakeTable:
        def delete(self, filter_str: str) -> None:
            pass

        def add(self, rows: list[dict]) -> None:
            upserted.extend(rows)

    seed_data.seed(FakeTable())

    assert len(upserted) == len(SEED_RECORDS)
    assert {row["old_symbol"] for row in upserted} == {r.old_symbol for r in SEED_RECORDS}
