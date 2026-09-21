"""Unit tests for PythonAdapter.resolve() and resolve_dependencies()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from resync.adapters.base import Dependency
from resync.adapters.python.adapter import PythonAdapter, PythonDependency
from resync.adapters.python.resolver import (
    ResolvedDependency,
    ResolverError,
    ResolveResult,
    resolve_dependencies,
)


def test_python_adapter_resolve_success(tmp_path: Path) -> None:
    adapter = PythonAdapter()
    deps: list[Dependency] = [PythonDependency(name="requests", version="*")]

    mock_result = ResolveResult(
        dependencies=[
            ResolvedDependency(name="requests", version="2.32.0"),
            ResolvedDependency(name="urllib3", version="2.2.0"),
        ],
        pylock_toml="",
    )

    with patch("resync.adapters.python.resolver.resolve", return_value=mock_result):
        lockfile = adapter.resolve(deps, "pinned")

    assert len(lockfile.dependencies) == 2
    assert lockfile.dependencies[0].name == "requests"
    assert lockfile.dependencies[0].version == "2.32.0"
    assert lockfile.dependencies[1].name == "urllib3"
    assert lockfile.dependencies[1].version == "2.2.0"


def test_python_adapter_resolve_empty() -> None:
    adapter = PythonAdapter()
    lockfile = adapter.resolve([], "pinned")
    assert len(lockfile.dependencies) == 0


def test_python_adapter_resolve_fallback_on_resolver_error(tmp_path: Path) -> None:
    adapter = PythonAdapter()
    deps: list[Dependency] = [PythonDependency(name="custom-pkg", version="1.0.0")]

    with patch("resync.adapters.python.resolver.resolve", side_effect=ResolverError("not found")):
        lockfile = adapter.resolve(deps, "pinned")

    # Gracefully falls back to returning the declared dependencies rather than crashing
    assert len(lockfile.dependencies) == 1
    assert lockfile.dependencies[0].name == "custom-pkg"
    assert lockfile.dependencies[0].version == "1.0.0"


def test_resolve_dependencies_version_formatting() -> None:
    deps: list[Dependency] = [
        PythonDependency(name="foo", version=">=1.0"),
        PythonDependency(name="bar", version="2.0.0"),
        PythonDependency(name="baz", version="*"),
    ]

    captured_reqs: list[str] = []

    def mock_resolve(reqs: list[str], repo_root: Path) -> ResolveResult:
        captured_reqs.extend(reqs)
        return ResolveResult(dependencies=[], pylock_toml="")

    with patch("resync.adapters.python.resolver.resolve", side_effect=mock_resolve):
        resolve_dependencies(deps, "pinned")

    assert captured_reqs == ["foo>=1.0", "bar==2.0.0", "baz"]
