"""Integration coverage for `resync sync --tier semantic` (cli/main.py), driven through Typer's CliRunner —
the same entry point a real terminal invocation goes through.

The local-model layer (`llm.llama_server.start`/`stop`, `llm.generator.draft_patch`,
`verification.critic.LlamaServerCritic`) is monkeypatched — no real GGUF model or `llama-server` binary is
available in this environment (see `llm/llama_server.py`'s module docstring), and that gap is already
documented, not hidden here. What *is* real: the knowledge-store lookup, `taxonomy.classify()`'s SEMANTIC
routing, and `_package_is_imported`'s real `ast-grep`-backed check — meaning, like
`test_sync_cli.py`'s existing mechanical-tier test, this fails in an environment without the real `ast-grep`
binary installed. That's the same already-documented, unrelated environment gap, not something this test
works around.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from resync.cli.main import app
from resync.knowledge import store
from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType
from resync.llm import llama_server
from resync.llm.generator import GeneratedPatch
from resync.verification.critic import CriticVerdict


@pytest.fixture
def seeded_semantic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(store, "embed_document", lambda text: [0.0] * store.EMBEDDING_DIM)
    db_path = store.default_db_path(tmp_path)
    db_path.parent.mkdir(parents=True)
    table = store.get_or_create_table(store.connect(db_path))
    # A MERGE record — never mechanical, per taxonomy.classify — is a real, already-used-elsewhere example
    # of a genuinely SEMANTIC classification (see knowledge/seed_data.py's own MERGE record for the pattern).
    record = KnowledgeRecord(
        package="somepkg",
        ecosystem="pypi",
        old_symbol="somepkg.connect",
        new_symbol=None,
        parameter="old_param",
        new_parameter="new_param",
        from_version="<2.0",
        to_version=">=2.0",
        rule_type=RuleType.MERGE,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.7,
    )
    store.upsert(table, [record])
    (tmp_path / "sample.py").write_text("import somepkg\n\nsomepkg.connect(old_param=1)\n")
    return tmp_path


def _fake_start(config: llama_server.LlamaServerConfig, **kwargs: object) -> llama_server.LlamaServerHandle:
    import subprocess
    import sys

    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    return llama_server.LlamaServerHandle(config=config, process=process)


def test_semantic_sync_without_model_flag_exits_with_a_clear_error(seeded_semantic_repo: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["sync", str(seeded_semantic_repo), "--tier", "semantic"])
    assert result.exit_code == 2
    assert "--model" in result.output


def test_semantic_sync_end_to_end_with_an_approved_patch(
    seeded_semantic_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "fake.gguf"
    model_path.write_bytes(b"not a real model")

    monkeypatch.setattr(llama_server, "start", _fake_start)
    monkeypatch.setattr(llama_server, "stop", lambda handle: handle.process.terminate())
    monkeypatch.setattr(
        "resync.llm.generator.draft_patch",
        lambda *a, **kw: GeneratedPatch(content="somepkg.connect(new_param=1)", raw_response=""),
    )
    monkeypatch.setattr(
        "resync.verification.critic.LlamaServerCritic.review",
        lambda self, patch, context: CriticVerdict(approved=True, concerns_considered=["checked rename"]),
    )

    runner = CliRunner()
    result = runner.invoke(
        app, ["sync", str(seeded_semantic_repo), "--tier", "semantic", "--model", str(model_path), "--apply"]
    )
    assert result.exit_code == 0, result.output
    assert (seeded_semantic_repo / "sample.py").read_text() == "somepkg.connect(new_param=1)"


def test_semantic_sync_never_writes_a_rejected_patch_even_with_apply(
    seeded_semantic_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "fake.gguf"
    model_path.write_bytes(b"not a real model")
    original = (seeded_semantic_repo / "sample.py").read_text()

    monkeypatch.setattr(llama_server, "start", _fake_start)
    monkeypatch.setattr(llama_server, "stop", lambda handle: handle.process.terminate())
    monkeypatch.setattr(
        "resync.llm.generator.draft_patch",
        lambda *a, **kw: GeneratedPatch(content="somepkg.connect(new_param=1)", raw_response=""),
    )
    monkeypatch.setattr(
        "resync.verification.critic.LlamaServerCritic.review",
        lambda self, patch, context: CriticVerdict(approved=False, rejection_reason="looks wrong"),
    )

    runner = CliRunner()
    result = runner.invoke(
        app, ["sync", str(seeded_semantic_repo), "--tier", "semantic", "--model", str(model_path), "--apply"]
    )
    assert result.exit_code == 0
    assert (seeded_semantic_repo / "sample.py").read_text() == original


def test_semantic_sync_skips_files_that_import_the_package_but_never_reference_the_changed_symbol(
    seeded_semantic_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for a real gap found in review: the semantic loop used to gate only on "the package
    is imported somewhere in the file" (`_package_is_imported`), far coarser than mechanical sync's actual
    per-symbol ast-grep matching. A file that imports `somepkg` for a completely unrelated reason — never
    calling the specific `somepkg.connect` this record is about — would still get sent to the LLM to "draft
    a fix," wasting a call and risking a spurious edit to a file that needed none. Confirms such a file is
    now correctly skipped: the generator is never even called for it."""
    unrelated_file = seeded_semantic_repo / "unrelated.py"
    unrelated_file.write_text("import somepkg\n\nx = somepkg.SOME_CONSTANT\n")
    original_unrelated = unrelated_file.read_text()

    model_path = tmp_path / "fake.gguf"
    model_path.write_bytes(b"not a real model")

    monkeypatch.setattr(llama_server, "start", _fake_start)
    monkeypatch.setattr(llama_server, "stop", lambda handle: handle.process.terminate())

    draft_calls: list[str] = []

    def _tracking_draft(change_description: str, file_contents: str, *a: object, **kw: object) -> GeneratedPatch:
        draft_calls.append(file_contents)
        return GeneratedPatch(content="somepkg.connect(new_param=1)", raw_response="")

    monkeypatch.setattr("resync.llm.generator.draft_patch", _tracking_draft)
    monkeypatch.setattr(
        "resync.verification.critic.LlamaServerCritic.review",
        lambda self, patch, context: CriticVerdict(approved=True, concerns_considered=["checked rename"]),
    )

    runner = CliRunner()
    result = runner.invoke(
        app, ["sync", str(seeded_semantic_repo), "--tier", "semantic", "--model", str(model_path), "--apply"]
    )
    assert result.exit_code == 0, result.output
    # The generator must only ever have been called for sample.py (which really calls somepkg.connect),
    # never for unrelated.py (which only imports the package for something else entirely).
    assert len(draft_calls) == 1
    assert "somepkg.connect(old_param=1)" in draft_calls[0]
    assert unrelated_file.read_text() == original_unrelated  # never touched
