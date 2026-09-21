# Tech stack and dependency rationale

This document is the detailed companion to the summary table in `docs/architecture.md`. Every choice below was
checked for current maintenance health, not just technical fit — see the Kùzu entry for why that check matters
in practice.

## Full dependency table (verified, resolved versions)

`pyproject.toml` declares version *floors* (`>=`), not exact pins — the table below is what a real, fresh
`uv sync --all-extras --all-groups` actually resolved to, confirmed by running it, not projected from the
floors. This resolution is committed as `uv.lock`, deliberately: Resync is dual-purpose (a `pip install`-able
library *and* a self-hosted server/CLI application), and for the application half specifically,
reproducibility across contributors and CI matters more than letting every clone re-resolve independently. A
consumer installing just the PyPI package still resolves freely against the floors in `pyproject.toml`,
unaffected by the lockfile.

| Package | Resolved version | Role | Why this one |
|---|---|---|---|
| `mcp` | 2.2.0 | Official MCP Python SDK | Confirmed to resolve and install cleanly. Pulls in `httpx2` and `mcp-types` as its own transitive dependencies — the SDK's real current dependency shape, found by inspecting the resolved tree (`uv tree`), not assumed from memory |
| `uvicorn` | 0.52.4 | HTTP transport for the MCP server | |
| `starlette` | 1.6.0 | HTTP transport, via `mcp` | Verified this is genuinely the official project (not a typosquat) by checking its package metadata directly. Now past 1.0 — newer than expected from general knowledge, and a concrete example of why this project checks live state instead of assuming |
| `lancedb` | 0.38.0 | Vector + full-text index | Confirmed healthy in an earlier pass (package health score 83/100, $30M Series A) |
| `kuzu` | 0.11.3 | Graph index (dev/test resolution) | This resolved version is from the original, now-archived PyPI listing — fine for development, but see `docs/architecture.md#decision-4-actively-maintained-kuzu-community-fork-for-graph-index`: production should point at the actively-maintained fork instead |
| `fastembed` | 0.8.0 | Embeddings | No `torch` anywhere in its resolved dependency tree — confirmed by inspecting the tree, not just trusting the package description |
| `httpx` | 0.28.1 | OSV.dev / GitHub Advisory / registry calls (Resync's own use — distinct from `mcp`'s internal `httpx2`) | |
| `sigstore` | 4.5.0 | Provenance verification | Official client, Python Cryptographic Authority / OpenSSF. `pyproject.toml`'s pin was still `>=3.0` despite this row already recording 4.5.0 — a real docs/pyproject inconsistency, found and fixed to `>=4.0` while building `verification/provenance.py` |
| `pypi-attestations` | 0.0.30 | PEP 740 attestation verification | PyPA's own purpose-built library — wraps `sigstore` for the specific "verify this PyPI package's Trusted Publishing attestation" task, so `verification/provenance.py` doesn't hand-roll that logic against raw `sigstore` |
| `pydantic` | 2.13.5 | Schema validation | Single version resolved across the entire tree — no v1/v2 split, confirmed by the resolution succeeding at all, since a split would have failed it |
| `tomli-w` | 1.2.0 | Writing back to `resync.toml` | `tomllib` (stdlib, 3.11+) is read-only |
| `typer` | 0.27.2 | CLI | |
| `rich` | 15.0.0 | CLI output | |
| `jinja2` | 3.1.6 | Review dashboard templates | |
| `pyyaml` | 6.0.3 | ast-grep YAML rule generation | |
| `ast-grep` (binary) | 0.45.3 | Structural patching | Installed separately (`pip install ast-grep-cli`), not part of the Python dependency tree — keeps the binding-version-mismatch surface at zero |
| `sandbox-runtime` | 0.2.0 | Isolated execution for `verification/sandbox.py` | Confirmed real and installable ahead of Phase 3 starting (see `docs/implementation-plan.md`'s Phase 3 readiness check), and declared in `pyproject.toml`'s `server` extra once Phase 3 actually built code depending on it — found missing from `pyproject.toml` entirely during Phase 3's own review pass despite being discussed here, and fixed then, not before |
| `cloudpickle` | 3.0+ | Serializes a closure across the process boundary for `verification/sandbox.py`'s Docker+gVisor fallback | Regular `pickle` can't handle arbitrary local closures/lambdas, which is exactly what the sandbox harness needs to ship across |
| `griffe` | 2.2+ | Static AST-based API diffing for `knowledge/extract_api_diff.py` | Found during Phase 1's research pass to correct an earlier, wrong claim in `docs/multi-language-adapters.md` that no mature Python API-diff tool existed — it does. A second, related wrong claim (that diffing `torch`-ecosystem packages like `peft` "never requires installing them" at all, full stop) was found and corrected during Phase 5: true for runtime *import*, but `griffe.load_pypi`/a plain `pip install` still installs the target's declared dependencies. `pip download --no-deps` + `search_paths` + `allow_inspection=False` is what actually avoids that — confirmed live: diffing real `peft` needs zero `torch` on disk |

Dev-only (`[dependency-groups]`, PEP 735 — never shipped to end users): `uv`, `ruff` 0.16.6, `mypy` 2.3.1,
`types-PyYAML`, `pytest` 9.1.1, `pytest-cov` 7.1.0, `hypothesis` 6.168.0, `pre-commit`.

## The one deliberate efficiency swap: no `torch` in the knowledge layer

`sentence-transformers` was the default assumption early in this project's design for running
`nomic-embed-text-v1.5`. It was replaced with `fastembed` specifically because pulling in the full PyTorch and
Transformers dependency chain just to embed text chunks would compete with — or simply not fit alongside — the
6–12GB VRAM budget reserved for the actual coding model. `fastembed` runs the same model through ONNX Runtime
instead, with quantized weights and no hidden PyTorch dependency, which is a real, stated design goal of the
library, not a marginal optimization. The result: zero `torch` dependency anywhere in the core knowledge-server
package. The only place a heavy ML runtime shows up at all is the separate `llama-server` process serving the
coding model — and that is run as its own process over an OpenAI-compatible HTTP endpoint, not imported
in-process via `llama-cpp-python`, for the same reason: process isolation, and it matches the client/server
split the whole architecture is built around rather than fighting it.

## The Kùzu correction, in full

The original `kuzudb/kuzu` project was archived in October 2025 after Apple acquired the company behind it
(Kùzu Inc.), and is now flagged inactive/deprecated by package health trackers, with no commits in six or more
months at time of review. This was discovered during an explicit "review for maintenance health" pass on the
stack — worth recording as a reminder that a good technical fit is not sufficient justification on its own; a
dependency review needs a maintenance-health check as a separate, explicit step. The fix: depend on the
actively-maintained `Vela-Engineering/kuzu` fork instead, which preserves the same Cypher interface and adds
concurrent multi-writer support relevant to Resync's own multi-adapter write pattern. Full reasoning and the
fallback option (Memgraph, if a single-company fork of an orphaned project is an unacceptable risk profile) is
in `docs/architecture.md#decision-4-actively-maintained-kuzu-community-fork-for-graph-index`.

## Dependency compatibility notes

- Keep `pydantic` on a single v2 minor range across the entire tree. `mcp` requires it, and a silent split
  between a v1-compatible library and a v2-only library is one of the most common real-world Python dependency
  conflicts.
- Keep `numpy` on one range compatible with both `lancedb` and `fastembed`'s `onnxruntime` dependency.
- Python 3.11 is the correct floor: `tomllib` is stdlib from 3.11 onward, and most of this stack has already
  dropped 3.9/3.10 support.

## Dependency scoping as a design principle

`pyproject.toml` splits dependencies two ways, deliberately: `[project.optional-dependencies]` holds only
genuine, user-facing installable extras (`server`, `cli`) that should appear in the published package's
metadata, while `[dependency-groups]` (PEP 735, resolved October 2024 and supported by `uv`, pip 25.1+, and
Poetry 2.3+) holds contributor-only tooling (`verify`, `dev`) that never ships to end users. Before PEP 735,
projects commonly stuffed lint/test tools into a fake `dev` extra under `optional-dependencies`, which meant
anyone inspecting the package on PyPI saw `pytest` and `ruff` listed as if they were a real feature a user
might opt into. This project doesn't make that mistake — a small thing, but thematically the wrong kind of
sloppiness for a project whose whole purpose is enforcing dependency hygiene on other codebases.

## A live risk worth tracking: the OpenAI/Astral acquisition

OpenAI has announced plans to acquire Astral — the company behind `uv`, `ruff`, and `ty`, all three of which
this project depends on for tooling. Unlike the Kùzu situation (ADR 0004), this is not treated as an
immediate red flag: all three tools are MIT-licensed, have very large existing community adoption, and remain
forkable if their direction changes in a way that stops serving this project's needs. It is, however, a
reason `ty` specifically stays optional-only rather than the default type checker — it was already in beta
with a stable release "targeted for 2026" before the acquisition was announced, and stacking that uncertainty
with new corporate-ownership uncertainty is exactly the kind of compounding risk this project's own "review for
maintenance health" principle (see the Kùzu entry above) exists to catch. `mypy` remains the default; revisit
`ty` once it has both a stable release and a settled maintenance situation post-acquisition.

## Naming and versioning

`resync` is already taken on PyPI — an unrelated, still-live ResourceSync library from 2013. The current
placeholder distribution name in `pyproject.toml` is `resync-mcp`; confirm availability before the first real
release, and consider `resyncai` as a fallback. The product name, GitHub repository name, and CLI command name
all stay `resync` regardless of the PyPI distribution name. Versioning follows SemVer 2.0.0, tags as `v0.1.0`,
with Conventional Commits driving changelog generation (see `CONTRIBUTING.md`).
