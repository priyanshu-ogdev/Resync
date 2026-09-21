from __future__ import annotations

from pathlib import Path

from resync.adapters.base import find_manifest_files


def test_find_manifest_files_root_and_nested(tmp_path: Path) -> None:
    # Root manifest
    root_pkg = tmp_path / "package.json"
    root_pkg.write_text("{}", encoding="utf-8")

    # Subproject manifests
    pkg_a = tmp_path / "packages" / "pkg-a"
    pkg_a.mkdir(parents=True)
    pkg_a_manifest = pkg_a / "package.json"
    pkg_a_manifest.write_text("{}", encoding="utf-8")

    pkg_b = tmp_path / "packages" / "pkg-b"
    pkg_b.mkdir(parents=True)
    pkg_b_manifest = pkg_b / "package.json"
    pkg_b_manifest.write_text("{}", encoding="utf-8")

    found = find_manifest_files(tmp_path, ["package.json"])
    assert len(found) == 3
    assert root_pkg in found
    assert pkg_a_manifest in found
    assert pkg_b_manifest in found


def test_find_manifest_files_prunes_excluded_directories(tmp_path: Path) -> None:
    # Excluded dirs should be skipped
    nm_pkg = tmp_path / "node_modules" / "some-dep" / "package.json"
    nm_pkg.parent.mkdir(parents=True)
    nm_pkg.write_text("{}", encoding="utf-8")

    git_pkg = tmp_path / ".git" / "package.json"
    git_pkg.parent.mkdir(parents=True)
    git_pkg.write_text("{}", encoding="utf-8")

    venv_pkg = tmp_path / ".venv" / "package.json"
    venv_pkg.parent.mkdir(parents=True)
    venv_pkg.write_text("{}", encoding="utf-8")

    build_pkg = tmp_path / "build" / "package.json"
    build_pkg.parent.mkdir(parents=True)
    build_pkg.write_text("{}", encoding="utf-8")

    # Valid src dir
    valid_pkg = tmp_path / "services" / "app" / "package.json"
    valid_pkg.parent.mkdir(parents=True)
    valid_pkg.write_text("{}", encoding="utf-8")

    found = find_manifest_files(tmp_path, ["package.json"])
    assert found == [valid_pkg]


def test_find_manifest_files_multiple_names(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("", encoding="utf-8")

    req = tmp_path / "requirements.txt"
    req.write_text("", encoding="utf-8")

    sub_req = tmp_path / "worker" / "requirements.txt"
    sub_req.parent.mkdir(parents=True)
    sub_req.write_text("", encoding="utf-8")

    found = find_manifest_files(tmp_path, ["pyproject.toml", "requirements.txt"])
    assert pyproject in found
    assert req in found
    assert sub_req in found
    assert len(found) == 3


def test_find_manifest_files_empty_repo(tmp_path: Path) -> None:
    found = find_manifest_files(tmp_path, ["pom.xml", "Cargo.toml"])
    assert found == []
