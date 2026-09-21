from __future__ import annotations

from pathlib import Path

from resync.adapters.base import BaseDiff
from resync.adapters.c_cpp.adapter import CCppAdapter
from resync.adapters.go.adapter import GoAdapter
from resync.adapters.java.adapter import JavaAdapter
from resync.adapters.kotlin.adapter import KotlinAdapter
from resync.adapters.python.adapter import PythonAdapter
from resync.adapters.rust.adapter import RustAdapter
from resync.adapters.typescript.adapter import TypeScriptAdapter
from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType


def test_base_diff_properties_and_unified_diff(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    old_content = "line1\nold_line\nline3\n"
    new_content = "line1\nnew_line\nline3\n"

    diff_changed = BaseDiff(file_path=sample, old_text=old_content, new_text=new_content)
    assert diff_changed.has_changes is True
    udiff = diff_changed.unified_diff()
    assert "--- a/" in udiff
    assert "+++ b/" in udiff
    assert "-old_line" in udiff
    assert "+new_line" in udiff

    diff_unchanged = BaseDiff(file_path=sample, old_text=old_content, new_text=old_content)
    assert diff_unchanged.has_changes is False
    assert diff_unchanged.unified_diff() == ""


def test_python_structural_patch_and_diff(tmp_path: Path) -> None:
    sample = tmp_path / "main.py"
    content = "from old_pkg import foo\nfoo(bar='baz')\n"
    sample.write_text(content, encoding="utf-8")

    record = KnowledgeRecord(
        package="old_pkg",
        ecosystem="pypi",
        old_symbol="old_pkg.foo",
        new_symbol="old_pkg.foo",
        parameter="bar",
        new_parameter="qux",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=1.0,
    )

    adapter = PythonAdapter()
    diff = adapter.structural_patch(sample, record)

    # Disk must not be mutated
    assert sample.read_text(encoding="utf-8") == content

    assert diff.has_changes is True
    assert "qux='baz'" in diff.new_text
    udiff = diff.unified_diff()
    assert "-foo(bar='baz')" in udiff
    assert "+foo(qux='baz')" in udiff


def test_typescript_structural_patch(tmp_path: Path) -> None:
    sample = tmp_path / "index.ts"
    content = "import { oldFunc } from 'pkg';\noldFunc(123);\n"
    sample.write_text(content, encoding="utf-8")

    record = KnowledgeRecord(
        package="pkg",
        ecosystem="npm",
        old_symbol="oldFunc",
        new_symbol="newFunc",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=1.0,
    )

    adapter = TypeScriptAdapter()
    diff = adapter.structural_patch(sample, record)

    assert sample.read_text(encoding="utf-8") == content
    assert diff.has_changes is True
    assert "newFunc(123)" in diff.new_text
    assert "oldFunc(123)" not in diff.new_text


def test_rust_structural_patch(tmp_path: Path) -> None:
    sample = tmp_path / "main.rs"
    content = "fn main() {\n    old_crate::legacy_call();\n}\n"
    sample.write_text(content, encoding="utf-8")

    record = KnowledgeRecord(
        package="old_crate",
        ecosystem="crates",
        old_symbol="old_crate::legacy_call",
        new_symbol="old_crate::modern_call",
        from_version="0.1",
        to_version="0.2",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=1.0,
    )

    adapter = RustAdapter()
    diff = adapter.structural_patch(sample, record)

    assert sample.read_text(encoding="utf-8") == content
    assert diff.has_changes is True
    assert "modern_call()" in diff.new_text


def test_go_structural_patch(tmp_path: Path) -> None:
    sample = tmp_path / "main.go"
    content = 'package main\n\nimport "oldpkg"\n\nfunc main() {\n\toldpkg.OldDo()\n}\n'
    sample.write_text(content, encoding="utf-8")

    record = KnowledgeRecord(
        package="oldpkg",
        ecosystem="go",
        old_symbol="oldpkg.OldDo",
        new_symbol="oldpkg.NewDo",
        from_version="v1.0.0",
        to_version="v2.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=1.0,
    )

    adapter = GoAdapter()
    diff = adapter.structural_patch(sample, record)

    assert sample.read_text(encoding="utf-8") == content
    assert diff.has_changes is True
    assert "NewDo()" in diff.new_text


def test_java_structural_patch(tmp_path: Path) -> None:
    sample = tmp_path / "App.java"
    content = (
        "package com.app;\n\n"
        "import com.example.helper.Helper;\n\n"
        "public class App {\n"
        "    public void test() {\n"
        "        Helper.oldMethod();\n"
        "    }\n"
        "}\n"
    )
    sample.write_text(content, encoding="utf-8")

    record = KnowledgeRecord(
        package="com.example.helper",
        ecosystem="maven",
        old_symbol="Helper.oldMethod",
        new_symbol="Helper.newMethod",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=1.0,
    )

    adapter = JavaAdapter()
    diff = adapter.structural_patch(sample, record)

    assert sample.read_text(encoding="utf-8") == content
    assert diff.has_changes is True
    assert "Helper.newMethod()" in diff.new_text


def test_kotlin_structural_patch(tmp_path: Path) -> None:
    sample = tmp_path / "App.kt"
    content = "package app\n\nimport org.example.oldFunction\n\nfun main() {\n    oldFunction(42)\n}\n"
    sample.write_text(content, encoding="utf-8")

    record = KnowledgeRecord(
        package="org.example",
        ecosystem="maven",
        old_symbol="oldFunction",
        new_symbol="newFunction",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=1.0,
    )

    adapter = KotlinAdapter()
    diff = adapter.structural_patch(sample, record)

    assert sample.read_text(encoding="utf-8") == content
    assert diff.has_changes is True
    assert "newFunction(42)" in diff.new_text


def test_cpp_structural_patch(tmp_path: Path) -> None:
    sample = tmp_path / "main.cpp"
    content = '#include <iostream>\n#include "mylib.h"\n\nint main() {\n    old_api_func();\n    return 0;\n}\n'
    sample.write_text(content, encoding="utf-8")

    record = KnowledgeRecord(
        package="mylib",
        ecosystem="conan",
        old_symbol="old_api_func",
        new_symbol="new_api_func",
        from_version="1.0",
        to_version="2.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=1.0,
    )

    adapter = CCppAdapter()
    diff = adapter.structural_patch(sample, record)

    assert sample.read_text(encoding="utf-8") == content
    assert diff.has_changes is True
    assert "new_api_func()" in diff.new_text
