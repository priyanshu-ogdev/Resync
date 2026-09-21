# Documentation Index

This directory contains the comprehensive technical documentation for Resync.

For a high-level introduction and quick start, see the root [`README.md`](../README.md). For technical depth, read the documentation in the following recommended order:

---

## Core Reading Order

1. **[`PRD.md`](PRD.md)** — **Product Requirements Document**
   The *what and why*: problem statement (code rot + agent slopsquatting), user personas, functional and non-functional requirements, verification gates, and explicit scope boundaries.

2. **[`architecture.md`](architecture.md)** — **System Architecture & Technical Design**
   The primary technical design authority:
   - System design, two-speed architecture, and core components.
   - **Integrated Architectural Decisions & Rationale**: The 6 foundational architectural decisions (MCP transport duality, differential equivalence, deterministic-first patching, embedded Kùzu graph, `resync.toml` policy persistence, and declarative multi-agent configuration).
   - **Research Foundations**: Theoretical grounding across hybrid RAG, Contextual Retrieval, Vul-RAG, and low-VRAM local execution.
   - **Competitive Landscape & Prior Art**: Deep analysis differentiating Resync from Dependency Director, Dependabot, Renovate, LADU, and Getafix.
   - **Testing & Release Strategies**: The multi-tiered testing pyramid (Hypothesis, integration, latency budgets) and SemVer / PyPI Trusted Publishing.

3. **[`workflow.md`](workflow.md)** — **Runtime Workflow & User Experience**
   The step-by-step lifecycle of a fix from an agent's keystroke through verification to PR delivery, plus the three dedicated user interaction surfaces:
   - Surface 1: Terminal CLI & Explainability Cards (`resync check --explain`, `resync explain <symbol>`).
   - Surface 2: GitHub PR Comments (auditable trust breakdowns and provenance metadata).
   - Surface 3: Starlette Review Dashboard (`http://127.0.0.1:8787/dashboard`, unified AST diff viewer, and live triage APIs).

4. **[`multi-language-adapters.md`](multi-language-adapters.md)** — **Polyglot Adapters & Plugin Engine**
   The three-tier plugin discovery engine and technical specifications for all 7 active language adapters: Python, Rust, TypeScript/JavaScript, Go, Kotlin/JVM, Java, and C/C++.

5. **[`tech-stack.md`](tech-stack.md)** — **Technology Stack & Dependencies**
   The complete resolved dependency manifest, maintenance evaluations (including the Kùzu community fork finding), zero-`torch` local embedding runtime, and Sigstore provenance verification.

6. **[`verification-report.md`](verification-report.md)** — **Real-World Empirical Verification Report**
   Empirical testing results and operational validation across real-world open-source codebases: Android/Kotlin/NDK (`goprivate`) and full-stack polyglot AI assistant (`HacktT`).

7. **[`implementation-plan.md`](implementation-plan.md)** — **Engineering Roadmap & Progress Audit**
   The 10-phase engineering roadmap, exit criteria, and status audits across all phases.

---

## Operational References

- **[`../AGENTS.md`](../AGENTS.md)** — Cross-tool instructions for AI coding agents working in this repository.
- **[`../installer/`](../installer/)** — Standalone single-launch installers (`install.exe`, `install.sh`).
- **[`../tools/`](../tools/)** — Internal developer utilities, diagnostics (`verify_install.py`), and cache cleaner (`clean.py`).
- **[`../examples/`](../examples/)** — Ready-to-use agent MCP configurations (`examples/mcp-configs/`) and GitHub Actions workflows (`examples/github-actions/`).
