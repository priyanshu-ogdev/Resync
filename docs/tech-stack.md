# Tech stack and dependency rationale

This document is the detailed companion to the summary table in `docs/architecture.md`. Every choice below was
checked for current maintenance health, not just technical fit — see the Kùzu entry for why that check matters
in practice.

## Full dependency table

| Package | Role | Why this one |
|---|---|---|
| `mcp` | Official MCP Python SDK | Tier-1 maintained; confirm it targets the 2026-07-28 stateless spec revision before pinning a version — see `docs/adr/0001-mcp-client-server-split.md` |
| `uvicorn` + `starlette` | HTTP transport for the MCP server | What the official SDK's Streamable HTTP transport runs on |
| `lancedb` | Vector + full-text index | Confirmed healthy at review time (package health score 83/100, $30M Series A, releases as recent as July 2026) |
| `kuzu` | Graph index | Point at the actively-maintained community fork (`Vela-Engineering/kuzu`), not the original — see `docs/adr/0004-graph-index-kuzu-fork.md`. Verify the exact install source from the fork's own docs before pinning; it was not independently confirmed to publish under a distinct PyPI name at review time |
| `fastembed` | Embeddings | ONNX Runtime-based, no PyTorch dependency, ships `nomic-embed-text-v1.5` support natively |
| `hypothesis` | Property-based equivalence testing | Mature, over a decade of production use, no maintenance concerns |
| `pytest` | Test runner | Standard |
| `httpx` | OSV.dev / GitHub Advisory / registry calls | Modern async client, actively maintained, the current standard over `requests` for this kind of use |
| `sigstore` | Provenance verification | Official client, maintained under the Python Cryptographic Authority / OpenSSF umbrella |
| `pydantic` (v2) | Schema validation | Required transitively by `mcp` — pin v2 everywhere to avoid a silent v1/v2 split across the dependency tree, one of the most common real-world Python dependency conflicts |
| `tomli-w` | Writing back to `resync.toml` | `tomllib` (stdlib, Python 3.11+) is read-only; this is the standard companion for writes |
| `typer` | CLI | Click-based, current standard for Python CLIs |
| `ast-grep` | Structural patching | Installed as a standalone binary (cargo/npm/release download), not a Python binding — keeps the binding-version-mismatch surface at zero |

Dev-only: `uv` (Rust-based resolver and package manager, meaningfully faster installs and lockfile resolution
than pip/Poetry, and the current default for new Python projects), `ruff` (lint + format in one tool,
replacing flake8/black/isort), and either `mypy` (mature, safe default) or `ty` (Astral's newer Rust-based type
checker — use it if proven stable enough on your machines, `mypy` otherwise).

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
in `docs/adr/0004-graph-index-kuzu-fork.md`.

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
