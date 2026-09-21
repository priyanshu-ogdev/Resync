# Multi-language adapters

The core (RAG, resolver invocation, sandboxing, trust scoring, PR generation, `resync.toml` handling) is
language-agnostic. Each supported language plugs in by implementing five functions and declaring its own
detection metadata. This document specifies each function's contract, the concrete tool each adapter wraps,
and how the auto-discovery engine activates adapters at runtime.

---

## Auto-discovery architecture

Resync discovers language adapters at startup via a **three-tier plugin engine** in `adapters/registry.py`.
No manual registration is required — adding a new language is dropping a new folder.

### Tier 1 — pip entry-points (third-party adapters)

Any pip package can expose new language support by registering under the `resync.adapters` entry-points group:

```toml
# In resync-adapter-ruby/pyproject.toml
[project.entry-points."resync.adapters"]
ruby = "resync_adapter_ruby:RubyAdapter"
```

After `pip install resync-adapter-ruby`, the Ruby adapter is auto-discovered on next startup — zero Resync
source changes required. Entry-point adapters override built-in ones with the same `name`, enabling drop-in
overrides and ecosystem-specific forks.

### Tier 2 — Built-in directory scan

Walks `resync/adapters/*/adapter.py`, imports each, reads `METADATA` and `ADAPTER_CLASS` at module level.
Built-in adapters follow exactly the same contract as third-party adapters.

### Tier 3 — PATH capability gating

Each adapter declares `required_tools: list[str]`. The registry checks `shutil.which(t)` for each. Adapters
whose required tools are absent are silently skipped rather than failing at runtime. `optional_tools` are
used when available and gracefully degraded when absent.

---

## `AdapterMetadata` — the declarative plugin contract

Every adapter module exposes two module-level exports:

```python
METADATA = AdapterMetadata(
    name="kotlin",  # unique ID
    ecosystem="maven",  # OSV ecosystem name
    display_name="Kotlin / JVM",  # shown in resync doctor / resync info
    # Repo-side signals (hints — presence activates the adapter)
    manifest_files=["build.gradle.kts", "build.gradle", "pom.xml"],
    manifest_globs=["**/*.kt", "**/*.kts"],
    exclude_dirs=["build", ".gradle", ".git"],
    # System-side capability gating
    required_tools=[],  # must be on PATH — empty = always activates
    optional_tools=["gradle", "mvn", "java"],
    priority=60,  # higher = preferred in polyglot repos
)
ADAPTER_CLASS = KotlinAdapter
```

---

## The adapter interface

```
parse_manifest(repo_path) -> list[Dependency]
    Read the ecosystem's lockfile/manifest into a normalized dependency list.

resolve(dependencies, target_profile) -> ResolvedLockfile
    Shell out to the ecosystem's native dependency resolver against a chosen profile
    (latest / pinned / security-only / date-based). Never reimplement a solver.

extract_api_diff(package, version_old, version_new) -> list[KnowledgeRecord]
    Produce the structured old_symbol → new_symbol → rule_type → confidence records
    defined in docs/architecture.md#knowledge-layer.

structural_patch(file, knowledge_record) -> Diff
    Apply a mechanical fix via the shared ast-grep engine.

capture_deprecation_signals(test_run_output) -> list[DeprecationWarning]
    Parse the ecosystem's own compiler/runtime warning format for live drift signals.
```

---

## Built-in adapters (7, as of this writing)

| Language | Ecosystem | Priority | Required tools | Status |
|---|---|---|---|---|
| Python | pypi | 100 | none | **Built** |
| Rust | crates.io | 80 | none (cargo optional) | **Built** |
| TypeScript / JS | npm | 75 | none (npm/tsc optional) | **Built** |
| Go | go | 70 | `go` binary | **Built** |
| Kotlin / JVM | maven | 60 | none (./gradlew self-contained) | **Built** |
| Java | maven | 55 | none (mvn optional) | **Built** |
| C / C++ | conan | 40 | none (cmake/conan optional) | **Built** |

---

## Python (primary, built for the flagship demo)

- `parse_manifest`: reads `pyproject.toml` / `requirements.txt` / lockfiles from `uv`, Poetry, or `pip-compile`.
- `resolve`: shells out to `uv` (preferred, fastest) or `pip-compile`/Poetry. **Built** —
  `resolve/resolver.py` wraps `uv pip compile - --format pylock.toml`, verified against the real binary
  (command shape, exit-code-based error classification, resync.toml pin honoring). See
  `docs/implementation-plan.md`'s Phase 5 entry for the full account, including a real assumption
  (`uv add --dry-run`) that running the real binary caught before it shipped.
- `extract_api_diff`: `griffe` — static/AST-based, purpose-built for diffing two loadable versions of a
  package's public API into typed `Breakage` objects, no runtime import required.
- `structural_patch`: `ast-grep --lang python`.
- `capture_deprecation_signals`: Python's own `DeprecationWarning`/`FutureWarning` from a test run.

## Rust

- `parse_manifest`: `Cargo.toml` / `Cargo.lock`.
- `resolve`: `cargo update` / `cargo add --precise`.
- `extract_api_diff`: `cargo-semver-checks` — already outputs structured "what broke, why" records.
- `structural_patch`: `ast-grep --lang rust`, plus `cargo fix` for edition migrations.
- `capture_deprecation_signals`: `#[deprecated]`-attribute warnings from `cargo build` or `cargo clippy`.

## TypeScript / JavaScript

- `parse_manifest`: `package.json` / lockfiles from npm, yarn, or pnpm.
- `resolve`: shells out to whichever of npm/yarn/pnpm the project already uses.
- `extract_api_diff`: TypeScript Compiler API, diffing public `.d.ts` surfaces between versions.
- `structural_patch`: `ast-grep --lang ts` / `--lang tsx`.
- `capture_deprecation_signals`: `@deprecated` JSDoc tags surfaced by `tsc` diagnostics.

## Go

- `parse_manifest`: `go.mod` `require` blocks (exact filename + block syntax both handled).
- `resolve`: `go mod tidy` / `go list -m all`. **Requires `go` binary on PATH.**
- `extract_api_diff`: `go-apidiff` (optional, `golang.org/x/exp/cmd/apidiff`).
- `structural_patch`: `ast-grep --lang go`.
- `capture_deprecation_signals`: `go vet` and `staticcheck` output.

## Kotlin / JVM

- `parse_manifest`: `build.gradle.kts`, `build.gradle` (regex for `implementation(...)`, `api(...)`,
  `testImplementation(...)`), and `pom.xml` `<dependency>` blocks.
- `resolve`: `./gradlew dependencies` (Gradle wrapper, self-contained) or `mvn dependency:list`.
  **No system-level `gradle` binary required** — the Gradle wrapper ships with the project.
- `extract_api_diff`: `japicmp` or `kotlin-binary-compatibility-validator` (not yet wired).
- `structural_patch`: `ast-grep --lang kotlin`.
- `capture_deprecation_signals`: Kotlin compiler warning pattern `w: file.kt:line: ... is deprecated`.

## Java

- `parse_manifest`: `pom.xml` `<dependency>` XML blocks (parsed without requiring `mvn`).
- `resolve`: `mvn dependency:resolve` (optional tool).
- `extract_api_diff`: `japicmp` or `revapi`.
- `structural_patch`: `ast-grep --lang java`.
- `capture_deprecation_signals`: `javac -Xlint:deprecation` output.

## C / C++

- `parse_manifest`: `conanfile.txt` `[requires]` section and `vcpkg.json` dependency names.
- `resolve`: `conan install .` (optional tool).
- `extract_api_diff`: `abi-compliance-checker` (optional tool).
- `structural_patch`: `ast-grep --lang c` or `--lang cpp` (auto-detected from file extension).
- `capture_deprecation_signals`: GCC/Clang `-Wdeprecated-declarations` warning pattern.

---

## Writing a third-party adapter

To add a new language (e.g. Ruby) without modifying Resync itself:

1. Create a package `resync-adapter-ruby` with a single module `resync_adapter_ruby/__init__.py`:

```python
from resync.adapters.base import AdapterMetadata, ...

METADATA = AdapterMetadata(
    name="ruby",
    ecosystem="rubygems",
    display_name="Ruby",
    manifest_files=["Gemfile", "Gemfile.lock", ".gemspec"],
    manifest_globs=["**/*.rb"],
    exclude_dirs=[".git", "vendor/bundle"],
    required_tools=["ruby"],
    optional_tools=["bundler", "rubocop"],
    priority=65,
)

class RubyAdapter:
    @property
    def ecosystem(self) -> str:
        return "rubygems"

    def parse_manifest(self, repo_path): ...
    def resolve(self, dependencies, target_profile): ...
    def extract_api_diff(self, package, version_old, version_new): ...
    def structural_patch(self, file_path, record): ...
    def capture_deprecation_signals(self, test_run_output): ...

ADAPTER_CLASS = RubyAdapter
```

2. Register the entry-point in `pyproject.toml`:

```toml
[project.entry-points."resync.adapters"]
ruby = "resync_adapter_ruby:RubyAdapter"
```

3. Publish to PyPI and install:

```bash
pip install resync-adapter-ruby
```

Ruby support appears automatically on next Resync startup — in `resync doctor`, `resync check`,
`verify_package` advisory lookups, and `resync info`. No Resync core code changes.

---

## Priority and polyglot repos

`get_adapters(repo_root)` returns **all** matching adapters for a repository (a TypeScript frontend +
Python backend repo gets both). `get_adapter(repo_root)` returns the highest-priority one. Priority is
defined per adapter and designed so Python (100) > Rust (80) > TypeScript (75) > Go (70) > Kotlin (60)
> Java (55) > C/C++ (40) — reflecting the primary demo target order, not quality ranking.
