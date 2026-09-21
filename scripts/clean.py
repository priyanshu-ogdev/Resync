"""Cross-platform repository cleanup script for Resync.

Safely removes Python bytecode (__pycache__, *.pyc), test/coverage caches
(.pytest_cache, .hypothesis, .coverage), linter/type-checker caches (.ruff_cache,
.mypy_cache), and build distribution artifacts (dist/, build/, *.egg-info).
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _clean_directories(root: Path, target_names: set[str], quiet: bool = False) -> int:
    removed_count = 0
    # Collect matching directories
    dirs_to_remove: list[Path] = []
    for p in root.rglob("*"):
        if p.is_dir() and p.name in target_names:
            # Do not traverse into .git or .venv
            if ".git" in p.parts or ".venv" in p.parts:
                continue
            dirs_to_remove.append(p)

    for d in dirs_to_remove:
        try:
            if not quiet:
                print(f"Removing directory: {d}")
            shutil.rmtree(d, ignore_errors=True)
            removed_count += 1
        except Exception as exc:
            print(f"Error removing {d}: {exc}")
    return removed_count


def _clean_files(root: Path, extensions: set[str], quiet: bool = False) -> int:
    removed_count = 0
    files_to_remove: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in extensions:
            if ".git" in p.parts or ".venv" in p.parts:
                continue
            files_to_remove.append(p)

    for f in files_to_remove:
        try:
            if not quiet:
                print(f"Removing file: {f}")
            f.unlink(missing_ok=True)
            removed_count += 1
        except Exception as exc:
            print(f"Error removing {f}: {exc}")
    return removed_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean repository caches, bytecode, and build artifacts.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root path (defaults to current dir)")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose file output")
    parser.add_argument(
        "--include-data", action="store_true", help="Also clean local LanceDB/Kuzu store cache (.resync/)"
    )
    args = parser.parse_args()

    repo_root = args.root.resolve()
    print(f"Cleaning repository artifacts in {repo_root}...")

    cache_dirs = {
        "__pycache__",
        ".pytest_cache",
        ".hypothesis",
        ".ruff_cache",
        ".mypy_cache",
        ".ty_cache",
        "dist",
        "build",
        "htmlcov",
    }

    if args.include_data:
        cache_dirs.add(".resync")

    # Clean cache directories
    dir_count = _clean_directories(repo_root, cache_dirs, quiet=args.quiet)

    # Clean egg-info directories
    egg_dirs = [
        p for p in repo_root.rglob("*.egg-info") if p.is_dir() and ".git" not in p.parts and ".venv" not in p.parts
    ]
    for egg in egg_dirs:
        if not args.quiet:
            print(f"Removing egg-info: {egg}")
        shutil.rmtree(egg, ignore_errors=True)
        dir_count += 1

    # Clean bytecode & test cache files
    file_extensions = {".pyc", ".pyo", ".pyd"}
    file_count = _clean_files(repo_root, file_extensions, quiet=args.quiet)

    # Clean coverage files
    cov_files = [repo_root / ".coverage", repo_root / "coverage.xml"]
    for cov in cov_files:
        if cov.exists():
            if not args.quiet:
                print(f"Removing coverage file: {cov}")
            cov.unlink(missing_ok=True)
            file_count += 1

    print(f"Cleanup complete: Removed {dir_count} directories and {file_count} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
