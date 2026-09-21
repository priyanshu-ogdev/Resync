# Resync — Runtime Workflow & User Experience

This document details the complete end-to-end runtime lifecycle of Resync, tracing a change from an agent's keystroke through verification, triage, and PR delivery, as well as the three primary user interaction surfaces.

---

## 1. End-to-End Runtime Lifecycle

```
[ Agent Writes Code ]
         │
         ▼
[ MCP Gate: verify_package, check_symbol_exists, explain_change ]
         ├───────────────────────────────┐
         ▼                               ▼
    (PASS: Valid API)            (FAIL: Drift/Hallucination)
         │                               │
         ▼                               ▼
   Agent Continues              Structured Feedback &
                                Suggested Replacement
                                to Agent Transcript
         │
         ▼
[ Scheduled Repository Sweep: resync check / sync ]
         │
         ▼
[ Knowledge Retrieval: Hybrid Vector + Graph + Router ]
         │
         ▼
[ Signature-Change Taxonomy Classification ]
         ├───────────────────────────────┐
         ▼                               ▼
  (Mechanical Fix)                (Semantic Fix)
         │                               │
         ▼                               ▼
  ast-grep Rewrite               Local LLM Synthesis
  (AppliedFix Guard)             + Adversarial Critic
         │                               │
         └───────────────┬───────────────┘
                         ▼
[ Tiered Differential / Property-Based Equivalence (Hypothesis) ]
                         │
                         ▼
[ Supply-Chain Provenance Gate (Sigstore + PEP 740 Attestations) ]
                         │
                         ▼
[ Impact Map & Decomposed Trust Scoring ]
                         │
                         ▼
[ Triage & Delivery: CLI Cards │ Review Dashboard │ PR Comments ]
                         │
                         ▼
[ Persistence: resync.toml Pins, Exceptions & Policies Updated ]
```

### Detailed Lifecycle Steps

1. **Agent Interception (Real-Time Prevention)**:
   Before committing to an import or dependency invocation, the coding agent calls Resync's deterministic MCP gate tools:
   - [`verify_package`](file:///d:/Resync/src/resync/server/tools.py): Verifies package existence, typosquatting risk, and known CVEs.
   - [`check_symbol_exists`](file:///d:/Resync/src/resync/server/tools.py): Verifies that a function or class exists in the pinned package version.
   - [`verify_patch_equivalence`](file:///d:/Resync/src/resync/server/patch_verification.py): Confirms deterministic structural equivalence without running unsafe code.
   - [`explain_change`](file:///d:/Resync/src/resync/server/tools.py): Returns root-cause narrative and remediation pathways.

2. **Structured Negative Feedback**:
   If an import or API call fails verification, Resync returns structured `VerificationResult` output with `suggested_replacement_raw` and trust breakdowns, prompting the agent to self-correct before writing broken code.

3. **Scheduled Drift Sweeps**:
   The background sweep (`resync check --explain` or `resync sync`) scans all 7 supported language manifests and AST call sites for deprecated usages, compiler warnings, and security advisories.

4. **Knowledge Retrieval**:
   For each flagged call site, the router retrieves structured `KnowledgeRecord` entries from the LanceDB vector store and Kùzu graph index via hybrid reciprocal rank fusion.

5. **Signature Taxonomy Classification**:
   The change is categorized as mechanical (rename, param reorder) or semantic (param split/merge, return shape alteration).

6. **Fix Synthesis**:
   - Mechanical transformations are compiled into tree-sitter AST rules and applied by `ast-grep`, with the `AppliedFix` ledger ensuring reorder operations remain idempotent.
   - Semantic changes are synthesized by the local LLM (`resync.llm.generator`) and reviewed by the adversarial critic (`resync.verification.critic.LlamaServerCritic`).

7. **Differential Equivalence Verification**:
   Property-based testing (Hypothesis) generates synthetic inputs across the function signature. Outputs of old and new code paths are compared side-by-side to guarantee behavioral parity.

8. **Supply-Chain Provenance Verification**:
   When upgrading dependencies, `resync resolve` verifies package signatures against Sigstore TUF roots and PyPI PEP 740 attestations.

9. **Decomposed Trust Scoring**:
   A 4-part trust score (`rule_match`, `test_suite`, `differential_equivalence`, `source_citation`) is calculated and attached to the proposal.

10. **Delivery & Review**:
    Changes are surfaced across the terminal UI, PR comments, or the Starlette Review Dashboard (`http://127.0.0.1:8787/dashboard`).

11. **Policy Persistence**:
    Human decisions (**Sync**, **Shift**, **Pin**, **Exception**) are committed to `resync.toml`, preventing repetitive triage.

---

## 2. User Interaction Surfaces

Resync features three dedicated interaction surfaces engineered for developer ergonomics and high information density.

### Surface 1: Terminal CLI & Explainability Cards

Built using `rich` for crisp, color-coded terminal interfaces:
- **`resync check --explain`**: Scans all manifests and call sites. For every flagged incompatibility, it displays an explainability card showing:
  - Affected file and exact line number.
  - Old vs. new symbol signatures.
  - Decomposed trust meters (Visual progress bars for Rule, Tests, Differential, Citation).
  - 4 actionable remediation commands:
    - **`[⚡ Sync]`**: Write AST replacement to disk (`resync sync --tier mechanical --apply`).
    - **`[🔄 Shift]`**: Request semantic migration or modernizing adapter.
    - **`[📌 Pin]`**: Add version ceiling to `resync.toml`.
    - **`[⏳ Exception]`**: Add temporary policy exception with mandatory expiration.
- **`resync explain <target>`**: Terminal deep-dive for any symbol or package showing changelog citations, deprecation paths, and copy-pasteable remediation commands.
- **`resync doctor`**: System-wide diagnostic matrix verifying all 7 language adapters, package managers, ast-grep binaries, local graph stores, and registry APIs.

### Surface 2: GitHub PR Review Comments

Every PR opened by Resync includes an auditable trust breakdown comment:

```markdown
### Resync Trust Breakdown

| Dimension | Score | Status | Details |
|:---|:---:|:---:|:---|
| **Rule Match** | `1.00` | PASS | Mechanical AST rewrite (`rename`) |
| **Test Suite** | `1.00` | PASS | Project unit tests passed |
| **Differential Equivalence** | `1.00` | PASS | 12 Hypothesis inputs, 0 behavioral divergences |
| **Source Citation** | `0.95` | PASS | Verified against upstream PyPI changelog |

**Composite Trust Score: 0.98 / 1.00**
**Change Type**: `rename` &middot; **Action**: `[⚡ Sync]`
```

When changes are sharded across large monorepos (following Google Rosie-style large-scale changes), each PR links back to the parent decision record so reviewers see the broader migration context.

### Surface 3: Starlette Review Dashboard (`/dashboard`)

The Review Dashboard runs natively on the MCP server's HTTP daemon (`resync serve --transport streamable-http` or `resync dashboard`):
- **Zero External Tooling**: Pure Vanilla HTML5, CSS3, and JavaScript—no Node/npm dependencies or SPA frameworks.
- **Glassmorphic Dark Theme**: High-contrast, dark-mode design system with semantic coloring (green for verified, amber for human triage, red for blocked).
- **KPI Ribbon**: Real-time counters for tracked dependencies, active pins, expiring exceptions, pending decisions, and repo trust score.
- **Side-by-Side AST Diff Viewer**: Live unified diff viewer generated directly from `ast_grep_runner.preview()`.
- **One-Click Action Execution**: Interactive buttons to apply **`[⚡ Sync]`**, **`[🔄 Shift]`**, **[📌 Pin]**, or **[⏳ Exception]**.
- **REST Endpoints**:
  - `GET /dashboard`: Main interactive interface.
  - `GET /api/dashboard/status`: System health and triage KPIs.
  - `GET /api/dashboard/decisions`: List of pending decisions with diffs and trust scores.
  - `POST /api/dashboard/decisions/apply`: Immediate execution of selected fixes and persistence to `resync.toml`.

---

## 3. Four Remediation Pathways

| Pathway | Action | When to Use | Mechanism |
|:---|:---|:---|:---|
| **`[⚡ Sync]`** | Update call sites | Standard library upgrades with mechanical drop-in replacements. | Writes structural AST patch to disk via `ast-grep`; records entry in `AppliedFix` ledger. |
| **`[🔄 Shift]`** | Modernize pattern | The old pattern is obsolete; migrating warrants architectural cleanup. | Routes migration to local LLM with adversarial critic review. |
| **`[📌 Pin]`** | Freeze dependency | Code cannot be upgraded due to hardware, CUDA, or ecosystem constraints. | Adds version ceiling entry to `resync.toml` `[[pin]]`. |
| **`[⏳ Exception]`** | Temporary freeze | Known tech debt that must be scheduled for a future sprint. | Adds `[[exception]]` to `resync.toml` with **mandatory `expires` date**. |
