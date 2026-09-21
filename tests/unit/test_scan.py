"""Unit tests for cli/scan.py.

Covers the parts of scan.py that don't need real network (discover_dependencies, resolve_pinned_version,
extract_fully_qualified_symbols) directly against real files written to tmp_path — not mocked ASTs or
fabricated pyproject data. Network-dependent paths (run_dependency_checks/run_symbol_checks) are exercised
indirectly via server/tools.py's own existing unit/integration tests, which already cover verify_package/
check_symbol_exists in isolation; re-testing the network behavior here would just duplicate that coverage
without adding anything scan.py itself is responsible for.
"""

from __future__ import annotations

from pathlib import Path

from resync.cli.scan import (
    discover_code_files,
    discover_dependencies,
    discover_python_files,
    extract_fully_qualified_symbols,
    is_actionable,
    resolve_pinned_version,
)
from resync.server.tools import VerificationOutcome


def test_discover_dependencies_reads_core_and_optional_groups(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'dependencies = ["pydantic>=2.0,<3", "typer>=0.12"]\n\n'
        "[project.optional-dependencies]\n"
        'server = ["mcp>=2.0", "httpx>=0.27"]\n'
        'cli = ["rich>=13.0"]\n'
    )
    discovered = discover_dependencies(tmp_path)
    assert discovered.names == ["httpx", "mcp", "pydantic", "rich", "typer"]
    assert discovered.ecosystem == "pypi"


def test_discover_dependencies_returns_empty_without_pyproject(tmp_path: Path) -> None:
    assert discover_dependencies(tmp_path).names == []


def test_discover_dependencies_handles_extras_and_url_requirements(tmp_path: Path) -> None:
    """Real PEP 508 requirement strings look nothing like a bare package name — brackets for extras, no
    space before version specifiers, sometimes a direct URL instead of a version at all. This is the exact
    kind of thing worth a real test rather than assuming the naive parse handles it."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["uvicorn[standard]>=0.30", "some-pkg @ https://example.com/pkg.whl"]\n'
    )
    discovered = discover_dependencies(tmp_path)
    assert discovered.names == ["some-pkg", "uvicorn"]


def test_resolve_pinned_version_prefers_uv_lock_over_environment(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "requests"\nversion = "2.31.0"\n')
    assert resolve_pinned_version("requests", tmp_path) == "2.31.0"


def test_resolve_pinned_version_falls_back_to_environment_without_uv_lock(tmp_path: Path) -> None:
    # pytest itself is guaranteed installed in the running environment this test executes in.
    version = resolve_pinned_version("pytest", tmp_path)
    assert version is not None


def test_resolve_pinned_version_returns_none_when_unresolvable(tmp_path: Path) -> None:
    assert resolve_pinned_version("definitely-not-a-real-package-xyz123", tmp_path) is None


def test_discover_python_files_skips_excluded_directories(tmp_path: Path) -> None:
    (tmp_path / "real.py").write_text("x = 1\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "skip_me.py").write_text("x = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip_me_too.py").write_text("x = 1\n")

    found = {p.name for p in discover_python_files(tmp_path)}
    assert found == {"real.py"}


def test_discover_code_files_multi_extensions_and_pruning(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "index.ts").write_text("console.log('hi');\n")
    (tmp_path / "Main.kt").write_text("fun main() {}\n")
    (tmp_path / "main.rs").write_text("fn main() {}\n")
    (tmp_path / "ignored.txt").write_text("hello\n")

    # In excluded dir
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "git_app.py").write_text("x = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.ts").write_text("x = 1\n")

    # Filter for .ts and .kt
    ts_kt = {p.name for p in discover_code_files(tmp_path, extensions=[".ts", "kt"])}
    assert ts_kt == {"index.ts", "Main.kt"}

    # All files excluding pruned
    all_files = {p.name for p in discover_code_files(tmp_path)}
    assert all_files == {"app.py", "index.ts", "Main.kt", "main.rs", "ignored.txt"}


def test_extract_fully_qualified_symbols_resolves_import_and_import_from(tmp_path: Path) -> None:
    py_file = tmp_path / "example.py"
    py_file.write_text(
        "import transformers\n"
        "from transformers import TrainingArguments\n"
        "\n"
        "args = TrainingArguments(no_cuda=True)\n"
        "model = transformers.PreTrainedModel.from_pretrained('x')\n"
    )
    symbols = extract_fully_qualified_symbols(py_file)
    assert "transformers.PreTrainedModel.from_pretrained" in symbols


def test_extract_fully_qualified_symbols_ignores_unimported_names(tmp_path: Path) -> None:
    """A bare local variable's attribute access (`my_var.foo.bar`) must never be reported as a fully-
    qualified symbol just because it has the right shape — it has to trace back to a real import."""
    py_file = tmp_path / "example.py"
    py_file.write_text("my_local_var = get_something()\nresult = my_local_var.foo.bar\n")
    assert extract_fully_qualified_symbols(py_file) == set()


def test_extract_fully_qualified_symbols_ignores_relative_imports(tmp_path: Path) -> None:
    py_file = tmp_path / "example.py"
    py_file.write_text("from . import sibling\nsibling.do_thing()\n")
    assert extract_fully_qualified_symbols(py_file) == set()


def test_extract_fully_qualified_symbols_returns_empty_for_unparseable_file(tmp_path: Path) -> None:
    py_file = tmp_path / "broken.py"
    py_file.write_text("def broken(:\n")
    assert extract_fully_qualified_symbols(py_file) == set()


def test_is_actionable() -> None:
    assert is_actionable(VerificationOutcome.OK) is False
    assert is_actionable(VerificationOutcome.PINNED) is False
    assert is_actionable(VerificationOutcome.PACKAGE_NOT_FOUND) is True
    assert is_actionable(VerificationOutcome.ADVISORY_FLAGGED) is True
    assert is_actionable(VerificationOutcome.CHECK_UNAVAILABLE) is True


def test_discover_dependencies_polyglot_repository(tmp_path: Path) -> None:
    """Polyglot repositories (e.g. Node frontend + Python backend) must detect
    and discover dependencies across both ecosystems simultaneously."""
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0", "next": "^14.0.0"}}')
    (tmp_path / "requirements.txt").write_text("fastapi>=0.100.0\nuvicorn>=0.20.0\n")

    discovered = discover_dependencies(tmp_path)
    assert "react" in discovered.names
    assert "next" in discovered.names
    assert "fastapi" in discovered.names
    assert "uvicorn" in discovered.names
    assert ("react", "npm") in discovered.items
    assert ("next", "npm") in discovered.items
    assert ("fastapi", "pypi") in discovered.items
    assert ("uvicorn", "pypi") in discovered.items
