"""Kotlin / JVM language adapter.

Uses the Gradle wrapper (./gradlew) or Maven (mvn) — whichever is present in the repo.
The Gradle wrapper is self-contained (no system-level gradle binary required), so
required_tools is empty; this adapter activates on any repo containing Gradle or Maven
manifests, regardless of the host environment.

ast-grep handles structural patching via --lang kotlin.
"""

from __future__ import annotations

import re
import tomllib
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
    name="kotlin",
    ecosystem="maven",
    display_name="Kotlin / JVM",
    manifest_files=[
        "build.gradle.kts",
        "build.gradle",
        "pom.xml",
        "settings.gradle.kts",
        "settings.gradle",
        "libs.versions.toml",
        "gradle/libs.versions.toml",
    ],
    manifest_globs=["**/*.kt", "**/*.kts", "**/build.gradle*", "**/libs.versions.toml"],
    exclude_dirs=["build", ".gradle", ".git", "target", "node_modules", ".venv", "venv"],
    required_tools=[],
    optional_tools=["gradle", "mvn", "java", "kotlin"],
    priority=60,
)

_GRADLE_DEP_RE = re.compile(
    r"""(?:implementation|api|testImplementation|compileOnly|runtimeOnly|kapt|annotationProcessor|ksp|coreLibraryDesugaring|androidTestImplementation|debugImplementation|releaseImplementation|classpath)\s*\(?\s*["']([^"']+)["']\s*\)?""",
    re.MULTILINE,
)
_VAL_ASSIGN_RE = re.compile(r"""(?:val|var|def|ext\.[a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s*=\s*["']([^"']+)["']""")
_POM_DEP_RE = re.compile(
    r"<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>"
    r"(?:\s*<version>([^<]*)</version>)?",
    re.DOTALL,
)


class KotlinDependency:
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class KotlinResolvedLockfile:
    def __init__(self, dependencies: list[Dependency]) -> None:
        self.dependencies = dependencies


class KotlinDiff(BaseDiff):
    """Kotlin AST-grep structural diff."""

    pass


class KotlinDeprecationWarning:
    def __init__(self, symbol: str, message: str, file_path: Path, line: int) -> None:
        self.symbol = symbol
        self.message = message
        self.file_path = file_path
        self.line = line


def _parse_gradle(text: str) -> list[KotlinDependency]:
    deps: list[KotlinDependency] = []
    seen: set[str] = set()
    val_map = dict(_VAL_ASSIGN_RE.findall(text))

    for match in _GRADLE_DEP_RE.finditer(text):
        coord = match.group(1).strip()
        parts = coord.split(":")
        if len(parts) >= 2:
            name = f"{parts[0]}:{parts[1]}"
            raw_version = parts[2] if len(parts) >= 3 else "*"
            if raw_version.startswith("$"):
                var_name = raw_version[1:].strip("{}")
                version = val_map.get(var_name, "*")
            else:
                version = raw_version
            if name not in seen:
                seen.add(name)
                deps.append(KotlinDependency(name=name, version=version))
    return deps


def _parse_version_catalog(text: str) -> list[KotlinDependency]:
    deps: list[KotlinDependency] = []
    seen: set[str] = set()
    try:
        data = tomllib.loads(text)
    except Exception:
        return deps

    versions: dict[str, str] = {}
    for k, v in data.get("versions", {}).items():
        if isinstance(v, str):
            versions[k] = v
        elif isinstance(v, dict):
            if "strictly" in v:
                versions[k] = str(v["strictly"])
            elif "prefer" in v:
                versions[k] = str(v["prefer"])

    for _, lib_val in data.get("libraries", {}).items():
        group: str = ""
        name: str = ""
        version: str = "*"

        if isinstance(lib_val, str):
            parts = lib_val.split(":")
            if len(parts) >= 2:
                group, name = parts[0], parts[1]
                if len(parts) >= 3:
                    version = parts[2]
        elif isinstance(lib_val, dict):
            if "module" in lib_val:
                parts = str(lib_val["module"]).split(":")
                if len(parts) >= 2:
                    group, name = parts[0], parts[1]
            else:
                group = str(lib_val.get("group", ""))
                name = str(lib_val.get("name", ""))

            if "version.ref" in lib_val:
                ref = str(lib_val["version.ref"])
                version = versions.get(ref, versions.get(ref.replace("-", ""), "*"))
            elif "version" in lib_val:
                v_entry = lib_val["version"]
                if isinstance(v_entry, str):
                    version = v_entry
                elif isinstance(v_entry, dict) and "ref" in v_entry:
                    version = versions.get(str(v_entry["ref"]), "*")

        if group and name:
            coord = f"{group.strip()}:{name.strip()}"
            if coord not in seen:
                seen.add(coord)
                deps.append(KotlinDependency(name=coord, version=version.strip()))

    return deps


def _parse_pom(text: str) -> list[KotlinDependency]:
    deps: list[KotlinDependency] = []
    seen: set[str] = set()
    for m in _POM_DEP_RE.finditer(text):
        group, artifact = m.group(1).strip(), m.group(2).strip()
        version = (m.group(3) or "*").strip()
        name = f"{group}:{artifact}"
        if name not in seen:
            seen.add(name)
            deps.append(KotlinDependency(name=name, version=version))
    return deps


class KotlinAdapter:
    """Kotlin / JVM language adapter. Supports Gradle DSL (Kotlin + Groovy), Version Catalogs, and Maven."""

    @property
    def ecosystem(self) -> str:
        return "maven"

    def parse_manifest(self, repo_path: Path) -> list[Dependency]:
        manifest_files = find_manifest_files(
            repo_path,
            ["build.gradle.kts", "build.gradle", "pom.xml", "libs.versions.toml"],
            METADATA.exclude_dirs,
        )

        deps_by_name: dict[str, str] = {}

        for mf in manifest_files:
            try:
                content = mf.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if mf.name == "libs.versions.toml":
                for d in _parse_version_catalog(content):
                    if d.name not in deps_by_name or deps_by_name[d.name] == "*":
                        deps_by_name[d.name] = d.version
            elif mf.name.startswith("build.gradle"):
                for d in _parse_gradle(content):
                    if d.name not in deps_by_name or (deps_by_name[d.name] == "*" and d.version != "*"):
                        deps_by_name[d.name] = d.version
            elif mf.name == "pom.xml":
                for d in _parse_pom(content):
                    if d.name not in deps_by_name or (deps_by_name[d.name] == "*" and d.version != "*"):
                        deps_by_name[d.name] = d.version

        return [KotlinDependency(name=k, version=v) for k, v in sorted(deps_by_name.items())]

    def resolve(self, dependencies: list[Dependency], target_profile: str) -> ResolvedLockfile:
        return KotlinResolvedLockfile(dependencies=dependencies)

    def extract_api_diff(self, package: str, version_old: str, version_new: str) -> list[KnowledgeRecord]:
        raise NotImplementedError(
            "Kotlin API diffing requires japicmp or kotlin-binary-compatibility-validator. "
            "Install japicmp and add a resync-adapter-kotlin-apidiff plugin."
        )

    def structural_patch(self, file_path: Path, record: KnowledgeRecord) -> Diff:
        """Generates a structural patch diff for record on file_path without modifying the file on disk."""
        return execute_structural_patch(file_path, record, language="kotlin", diff_factory=KotlinDiff)

    def capture_deprecation_signals(self, test_run_output: str) -> list[DeprecationWarning_]:
        warnings: list[DeprecationWarning_] = []
        pattern = re.compile(r"^w: ([^:]+):(\d+):\d+: warning: '([^']+)' is deprecated\. (.+)$", re.MULTILINE)
        for m in pattern.finditer(test_run_output):
            warnings.append(
                KotlinDeprecationWarning(
                    symbol=m.group(3),
                    message=m.group(4),
                    file_path=Path(m.group(1)),
                    line=int(m.group(2)),
                )
            )
        return warnings


ADAPTER_CLASS = KotlinAdapter
