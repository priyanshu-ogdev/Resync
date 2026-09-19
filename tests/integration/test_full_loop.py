"""The full detect -> retrieve -> patch loop, end to end, against real fixtures and real infrastructure —
this is Phase 5's exit criteria (docs/implementation-plan.md): "running the full loop against a
tests/fixtures repo... produces a correct, verified patch with no manual intervention."

Real `extract()` (real `pip download`, real `griffe`) produces a real `KnowledgeRecord`, which real
`ast_grep_runner` (real `ast-grep` binary) then uses to rewrite a real fixture file — no mocking anywhere in
this chain. See tests/fixtures/transformers-pipeline-param-rename/NOTES.md for the real, live-confirmed
rename this test is built around, and tests/fixtures/peft-param-rename/NOTES.md for a related, deliberately
*not*-fixed fixture documenting a genuine heuristic limitation this same pass found and chose not to rush a
fix for.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

griffe = pytest.importorskip("griffe")

from resync.adapters.python.extract_api_diff import extract  # noqa: E402
from resync.patch import ast_grep_runner  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"

pytestmark = pytest.mark.network


def test_full_loop_transformers_pipeline_rename(tmp_path: Path) -> None:
    if shutil.which("pip") is None or shutil.which("ast-grep") is None:
        pytest.skip("pip and ast-grep both required for the full loop")

    records = extract(
        package="transformers", old_ref="4.31.0", new_ref="4.32.0", from_version="4.31.0", to_version="4.32.0"
    )
    record = next(r for r in records if r.old_symbol.endswith("pipelines.pipeline") and r.parameter == "use_auth_token")
    assert record.new_parameter == "token"

    target = tmp_path / "sample.py"
    shutil.copy(FIXTURES / "transformers-pipeline-param-rename" / "sample.py", target)
    original = target.read_text()
    assert "use_auth_token=hf_token" in original

    preview_matches = ast_grep_runner.preview(record, target)
    assert len(preview_matches) == 1
    assert target.read_text() == original  # preview must never write

    applied_matches = ast_grep_runner.apply(record, target, repo_root=tmp_path)
    assert len(applied_matches) == 1

    rewritten = target.read_text()
    assert "token=hf_token" in rewritten
    assert "use_auth_token" not in rewritten


def test_full_loop_peft_gather_params_ctx_documents_a_real_heuristic_limitation(tmp_path: Path) -> None:
    """Companion to the success case above: this one confirms the correlation heuristic's real, known false
    positive (see tests/fixtures/peft-param-rename/NOTES.md) still applies to `module` when it shouldn't —
    written as an assertion, not just prose, so a future fix to the heuristic is a deliberate, visible
    change to this test rather than a silent behavior shift nobody notices."""
    if shutil.which("pip") is None:
        pytest.skip("pip required")

    records = extract(package="peft", old_ref="0.10.0", new_ref="0.12.0", from_version="0.10.0", to_version="0.12.0")
    record = next(r for r in records if r.old_symbol.endswith("gather_params_ctx") and r.parameter == "module")
    # Documents the known-wrong current behavior (see NOTES.md) — the structurally correct rename target is
    # "param" (same position), but the heuristic currently picks "fwd_module" (higher text similarity).
    # This assertion should be the first thing to change if/when the positional-tiebreaker fix lands.
    assert record.new_parameter == "fwd_module"
