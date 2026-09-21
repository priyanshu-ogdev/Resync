from __future__ import annotations

from pathlib import Path

from resync.adapters.python.adapter import PythonAdapter
from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType


def test_structural_patch_generates_diff_without_modifying_file(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    original_code = (
        "from transformers import AutoModel\nmodel = AutoModel.from_pretrained('bert', use_auth_token='xyz')\n"
    )
    sample.write_text(original_code, encoding="utf-8")

    record = KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.AutoModel.from_pretrained",
        new_symbol="transformers.AutoModel.from_pretrained",
        parameter="use_auth_token",
        new_parameter="token",
        from_version="4.30.0",
        to_version="4.35.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=1.0,
    )

    adapter = PythonAdapter()
    diff = adapter.structural_patch(sample, record)

    # File on disk must remain unchanged
    assert sample.read_text(encoding="utf-8") == original_code

    # Diff must reflect the rename
    assert diff.old_text == original_code
    assert "token='xyz'" in diff.new_text
    assert "use_auth_token" not in diff.new_text


def test_structural_patch_returns_unchanged_when_no_match(tmp_path: Path) -> None:
    sample = tmp_path / "other.py"
    code = "import os\nprint(os.getcwd())\n"
    sample.write_text(code, encoding="utf-8")

    record = KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.AutoModel.from_pretrained",
        new_symbol="transformers.AutoModel.from_pretrained",
        parameter="use_auth_token",
        new_parameter="token",
        from_version="4.30.0",
        to_version="4.35.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=1.0,
    )

    adapter = PythonAdapter()
    diff = adapter.structural_patch(sample, record)
    assert diff.old_text == code
    assert diff.new_text == code


def test_structural_patch_nonexistent_file(tmp_path: Path) -> None:
    non_existent = tmp_path / "missing.py"
    record = KnowledgeRecord(
        package="transformers",
        ecosystem="pypi",
        old_symbol="transformers.AutoModel",
        new_symbol="transformers.NewAutoModel",
        from_version="4.30.0",
        to_version="4.35.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=1.0,
    )

    adapter = PythonAdapter()
    diff = adapter.structural_patch(non_existent, record)
    assert diff.old_text == ""
    assert diff.new_text == ""
