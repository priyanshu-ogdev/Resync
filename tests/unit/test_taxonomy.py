from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType
from resync.patch.taxonomy import PatchStrategy, classify


def _record(rule_type: RuleType, confidence: float) -> KnowledgeRecord:
    kwargs = dict(
        package="pkg",
        ecosystem="pypi",
        old_symbol="pkg.func",
        new_symbol="pkg.func2" if rule_type != RuleType.REMOVED_NO_REPLACEMENT else None,
        from_version="1.0",
        to_version="2.0",
        rule_type=rule_type,
        source=RecordSource.API_DIFF_TOOL,
        confidence=confidence,
    )
    if rule_type == RuleType.REORDER:
        # KnowledgeRecord's own validator (schema.py) requires a real permutation for REORDER — this test
        # helper previously predated that validator and would now fail construction, not just the assertion.
        kwargs["old_param_order"] = ["a", "b"]
        kwargs["new_param_order"] = ["b", "a"]
    return KnowledgeRecord(**kwargs)


def test_removed_no_replacement_always_escalates_regardless_of_confidence() -> None:
    assert classify(_record(RuleType.REMOVED_NO_REPLACEMENT, confidence=0.99)) == PatchStrategy.ESCALATE


def test_high_confidence_rename_is_mechanical() -> None:
    assert classify(_record(RuleType.RENAME, confidence=0.98)) == PatchStrategy.MECHANICAL


def test_low_confidence_rename_falls_back_to_semantic() -> None:
    """A mechanical rule_type doesn't override a suspiciously low confidence — see taxonomy.py's docstring
    on why this is more than a bare rule_type.is_mechanical check."""
    assert classify(_record(RuleType.RENAME, confidence=0.5)) == PatchStrategy.SEMANTIC


def test_confidence_threshold_is_configurable_and_inclusive() -> None:
    record = _record(RuleType.REORDER, confidence=0.9)
    assert classify(record, confidence_threshold=0.9) == PatchStrategy.MECHANICAL
    assert classify(record, confidence_threshold=0.91) == PatchStrategy.SEMANTIC


def test_split_and_merge_are_never_mechanical_even_at_high_confidence() -> None:
    for rule_type in (
        RuleType.SPLIT,
        RuleType.MERGE,
        RuleType.RETURN_SHAPE_CHANGE,
        RuleType.BEHAVIOR_CHANGE,
    ):
        assert classify(_record(rule_type, confidence=0.99)) == PatchStrategy.SEMANTIC
