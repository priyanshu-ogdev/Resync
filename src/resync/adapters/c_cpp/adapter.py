"""C / C++ language adapter.

Supports projects using CMake, Conan, or bare Makefiles. No required tools — parses
`conanfile.txt` and `CMakeLists.txt` directly without running any build system.
ast-grep handles structural patching via `--lang c` or `--lang cpp`.

Optional tools: cmake, conan, gcc, clang, abi-compliance-checker (for API diff).
"""

from __future__ import annotations

import re
from pathlib import Path

from resync.adapters.base import (
    AdapterMetadata,
    BaseDiff,
    Dependency,
    DeprecationWarning_,
    Diff,
    ResolvedLockfile,
    execute_structural_patch,
    find_manifest_files,
)
from resync.knowledge.schema import KnowledgeRecord

METADATA = AdapterMetadata(
    name="c_cpp",
    ecosystem="conan",
    display_name="C / C++",
    manifest_files=[
        "conanfile.txt",
        "conanfile.py",
        "CMakeLists.txt",
        "Makefile",
        "meson.build",
        "vcpkg.json",
    ],
    manifest_globs=["**/*.c", "**/*.cpp", "**/*.cc", "**/*.cxx", "**/*.h", "**/*.hpp"],
    exclude_dirs=[
        "build",
        "cmake-build-debug",
        "cmake-build-release",
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "vendor",
    ],
    required_tools=[],
    optional_tools=["cmake", "conan", "gcc", "clang", "g++", "clang++", "abi-compliance-checker"],
    priority=40,
)

_CONAN_REQ_RE = re.compile(r"^([A-Za-z0-9_\-]+)/([^\s#@\[]+)", re.MULTILINE)
_VCPKG_DEP_RE = re.compile(r'"name"\s*:\s*"([^"]+)"')
_GCC_DEPRECATED_RE = re.compile(
    r"^(.+):(\d+):\d+: warning: .+ is deprecated \[-Wdeprecated-declarations\]",
    re.MULTILINE,
)


class CCppDependency:
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class CCppResolvedLockfile:
    def __init__(self, dependencies: list[Dependency]) -> None:
        self.dependencies = dependencies


class CCppDiff(BaseDiff):
    """C / C++ AST-grep structural diff."""

    pass


class CCppDeprecationWarning:
    def __init__(self, symbol: str, message: str, file_path: Path, line: int) -> None:
        self.symbol = symbol
        self.message = message
        self.file_path = file_path
        self.line = line


class CCppAdapter:
    """C / C++ language adapter. Parses Conan, CMake, and vcpkg manifests."""

    @property
    def ecosystem(self) -> str:
        return "conan"

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        conan_files = find_manifest_files(repo_path, ["conanfile.txt"], METADATA.exclude_dirs)
        vcpkg_files = find_manifest_files(repo_path, ["vcpkg.json"], METADATA.exclude_dirs)

        deps_by_name: dict[str, str] = {}

        for conanfile in conan_files:
            try:
                text = conanfile.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            in_requires = False
            for line in text.splitlines():
                line = line.strip()
                if line.lower() == "[requires]":
                    in_requires = True
                    continue
                if line.startswith("[") and in_requires:
                    break
                if in_requires and line and not line.startswith("#"):
                    m = _CONAN_REQ_RE.match(line)
                    if m:
                        pkg_name, pkg_ver = m.group(1), m.group(2)
                        if pkg_name not in deps_by_name or (deps_by_name[pkg_name] == "*" and pkg_ver != "*"):
                            deps_by_name[pkg_name] = pkg_ver

        for vcpkg in vcpkg_files:
            try:
                text = vcpkg.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in _VCPKG_DEP_RE.finditer(text):
                pkg_name = m.group(1)
                if pkg_name not in deps_by_name:
                    deps_by_name[pkg_name] = "*"

        return [CCppDependency(name=k, version=v) for k, v in sorted(deps_by_name.items())]

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        return CCppResolvedLockfile(dependencies=dependencies)

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        raise NotImplementedError(
            "C/C++ API diffing requires abi-compliance-checker. Install: https://lvc.github.io/abi-compliance-checker/"
        )

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        """Generates a structural patch diff for record on file_path without modifying the file on disk."""
        lang = "cpp" if file_path.suffix in (".cpp", ".cc", ".cxx", ".hpp") else "c"
        return execute_structural_patch(file_path, record, language=lang, diff_factory=CCppDiff)

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        """Parse GCC/Clang -Wdeprecated-declarations output."""
        warnings: list[DeprecationWarning_] = []
        for m in _GCC_DEPRECATED_RE.finditer(test_run_output):
            warnings.append(
                CCppDeprecationWarning(
                    symbol="",
                    message="-Wdeprecated-declarations",
                    file_path=Path(m.group(1)),
                    line=int(m.group(2)),
                )
            )
        return warnings


ADAPTER_CLASS = CCppAdapter
