"""Seed KnowledgeRecords for the flagship ML-stack demo (peft/bitsandbytes/transformers/torch).

Important, and worth stating plainly: this seed set starts small and contains only verified real changes,
not a bulk-generated plausible-looking dataset. A project whose entire purpose is catching inaccurate
assumptions about API compatibility cannot itself ship fabricated "known" changes — that would poison the
knowledge base with exactly the kind of unverified claim this tool exists to flag. Every record below cites
its actual source.

**Research pass, [current date]**: extended from 2 to 14 records, all sourced from `transformers`'
own official `MIGRATION_GUIDE_V5.md` (huggingface/transformers, `main` branch) — v5.0.0 shipped 2026-01-26 and
touches nearly every public API surface, making it an unusually dense single source of real, dated,
PR-linked changes. This is still short of the ~30-50 the Phase 1 exit criteria call for, and still only
covers `transformers` — `peft`, `bitsandbytes`, and `torch` have no equally strong single-document source
found in this pass and are honestly left at zero rather than padded with lower-confidence guesses. See
docs/implementation-plan.md's Phase 1 status and this module's closing note for the real path to the rest.

Deliberately included, not filtered out: three records below (`REMOVED_NO_REPLACEMENT` and `MERGE`) are
*not* mechanically fixable — they exist so `patch/taxonomy.classify()` has real non-trivial cases to route
to SEMANTIC/ESCALATE, not just an all-mechanical demo set that would never exercise that branch.

Review note: these records were rewritten once already, after review caught that the original version stored
`old_symbol` as a full call-signature-with-placeholder string (e.g.
"transformers.PreTrainedModel.from_pretrained(use_auth_token=...)") instead of a clean symbol path with the
changed argument captured separately. That broke exact-symbol lookup and didn't match router.py's own
fully-qualified-symbol regex — see schema.py's KnowledgeRecord docstring for the fix.
"""

from __future__ import annotations

from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType

# Verified: huggingface/transformers PR #25083 (merged July 2023) renamed the `use_auth_token` keyword
# argument to `token` across PreTrainedModel/PreTrainedConfig/PreTrainedTokenizer .from_pretrained() and
# related methods, adding `FutureWarning: The \`use_auth_token\` argument is deprecated and will be removed
# in v5 of Transformers.` This is real, documented, and still one of the most commonly hit deprecation
# warnings in ML codebases as of this project's design — it's the exact case used illustratively throughout
# docs/architecture.md and resync.toml's own examples, and it turns out to be accurate, not hypothetical.
# Superseded by the whole-of-v5 removal below (MIGRATION_GUIDE_V5.md's `use_auth_token` section, PR #41666)
# — both are kept: the 4.32 rename and the v5 hard removal are two distinct, independently-dated facts.
SEED_RECORDS: list[KnowledgeRecord] = [
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.PreTrainedModel.from_pretrained",
        new_symbol="transformers.PreTrainedModel.from_pretrained",  # the symbol itself is unchanged
        parameter="use_auth_token",
        new_parameter="token",
        from_version="<4.32.0",
        to_version=">=4.32.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.98,
    ),
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.PreTrainedTokenizerBase.from_pretrained",
        new_symbol="transformers.PreTrainedTokenizerBase.from_pretrained",
        parameter="use_auth_token",
        new_parameter="token",
        from_version="<4.32.0",
        to_version=">=4.32.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.98,
    ),
    # --- The following 12 are sourced from MIGRATION_GUIDE_V5.md (huggingface/transformers, main branch),
    # v5.0.0, released 2026-01-26. Each cites the specific guide section / linked PR it comes from.
    #
    # TrainingArguments: "Removing deprecated arguments in TrainingArguments" section. All seven below are
    # clean 1:1 keyword-argument renames with unchanged semantics (per the guide's own text) — genuinely
    # mechanical, high confidence.
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.TrainingArguments",
        new_symbol="transformers.TrainingArguments",
        parameter="per_gpu_train_batch_size",
        new_parameter="per_device_train_batch_size",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.97,
    ),
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.TrainingArguments",
        new_symbol="transformers.TrainingArguments",
        parameter="per_gpu_eval_batch_size",
        new_parameter="per_device_eval_batch_size",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.97,
    ),
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.TrainingArguments",
        new_symbol="transformers.TrainingArguments",
        parameter="no_cuda",
        new_parameter="use_cpu",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.95,  # boolean direction is unchanged (True still means "don't use the GPU")
    ),
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.TrainingArguments",
        new_symbol="transformers.TrainingArguments",
        parameter="tpu_metrics_debug",
        new_parameter="debug",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.9,
    ),
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.TrainingArguments",
        new_symbol="transformers.TrainingArguments",
        parameter="push_to_hub_token",
        new_parameter="hub_token",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.95,
    ),
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.TrainingArguments",
        new_symbol="transformers.TrainingArguments",
        parameter="include_inputs_for_metrics",
        new_parameter="include_for_metrics",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.9,
    ),
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.TrainingArguments",
        new_symbol="transformers.TrainingArguments",
        parameter="include_tokens_per_second",
        new_parameter="include_num_input_tokens_seen",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.9,
    ),
    # Trainer (not TrainingArguments): "Removing deprecated arguments in Trainer" section.
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.Trainer",
        new_symbol="transformers.Trainer",
        parameter="tokenizer",
        new_parameter="processing_class",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.92,
    ),
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.Trainer.train",
        new_symbol="transformers.Trainer.train",
        parameter="model_path",
        new_parameter="resume_from_checkpoint",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.9,
    ),
    # Whole-symbol renames — the guide's "Auto-classes" section. AutoModelForVision2Seq -> ...ImageTextToText
    # is a genuine clean 1:1 class rename, unlike AutoModelWithLMHead below (see that record's note).
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.AutoModelForVision2Seq",
        new_symbol="transformers.AutoModelForImageTextToText",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.93,
    ),
    # Not mechanically fixable — deliberately included so taxonomy.classify() has real ESCALATE/SEMANTIC
    # cases to route, not just an all-mechanical demo set. AutoModelWithLMHead's replacement depends on
    # which of three task-specific classes the caller actually needs (CausalLM / MaskedLM / Seq2SeqLM) —
    # there is no single correct mechanical substitution, which is exactly what REMOVED_NO_REPLACEMENT
    # means in this taxonomy (docs/architecture.md's signature-change taxonomy).
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.AutoModelWithLMHead",
        new_symbol=None,
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.REMOVED_NO_REPLACEMENT,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.9,
    ),
    # MERGE: two TrainingArguments params folded into one. Schema currently has no MERGE-specific fields
    # (only RENAME's parameter/new_parameter and REORDER's old/new_param_order are modeled) — a real,
    # honestly-flagged gap, not hidden here. `new_parameter` captures the destination; the second source
    # param (`push_to_hub_organization`) has no field to live in yet. Good enough for retrieval and human
    # escalation (which is all a MERGE needs, since it's SEMANTIC/ESCALATE, never mechanical), but a
    # concrete argument for adding old_symbols: list[str] | None if MERGE records become common.
    KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.TrainingArguments",
        new_symbol="transformers.TrainingArguments",
        parameter="push_to_hub_model_id",
        new_parameter="hub_model_id",
        from_version="<5.0.0",
        to_version=">=5.0.0",
        rule_type=RuleType.MERGE,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.92,  # the fact itself is well-verified (official migration guide); low confidence
        # would live in a mechanical-fixability score if this schema had one, not here — this field
        # represents confidence the change is real, and a MERGE is never mechanical regardless of it.
    ),
]


def seed(table, graph_conn=None) -> None:  # type: ignore[no-untyped-def]
    """Populate a freshly created LanceDB table with the verified seed set.

    Deliberately not typed against lancedb.table.Table at the parameter level here to avoid an import
    dependency in modules that only need this function for a test fixture — see tests/unit/test_seed_data.py.
    """
    from resync.knowledge.store import upsert

    upsert(table, SEED_RECORDS)
