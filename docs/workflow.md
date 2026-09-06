# Resync — End-to-end workflow

This walks one fix through the entire system, from an agent's first keystroke to a merged PR. Each step
references the architecture component responsible for it — see `docs/architecture.md` for why each piece is
built the way it is.

1. **An agent starts writing code.** Before committing to an import or install, it — or Resync's MCP gate,
   intercepting the call — checks `verify_package` / `check_symbol_exists` against the registry, advisory
   feeds, and the pinned lockfile. *(Real-time prevention.)*

2. **If the check fails**, a structured result is returned to the calling agent, not a silent rewrite: what's
   wrong, and where known, the correct replacement. The agent incorporates this into its own next turn, visible
   in its own transcript. *(Deployment model — guardrails in tools, not prompts.)*

3. **Independently, the scheduled sweep runs** on its risk-tiered cadence, scanning the existing codebase's
   dependency graph and captured deprecation warnings for drift that accumulated without any agent's
   involvement. *(Two speeds — scheduled correction.)*

4. **For each flagged usage**, the knowledge layer retrieves the relevant record, and the signature-change
   taxonomy classifies what kind of fix is required. *(Knowledge layer, signature taxonomy.)*

5. **The Impact Map** determines blast radius and, for ambiguous cases, either matches an established repo
   precedent, applies a persisted policy from `resync.toml`, or elicits a human decision via MCP's
   `input_required` flow. *(The Impact Map.)*

6. **Mechanical fixes** are applied directly via ast-grep; **semantic fixes** are drafted by the local
   quantized model and passed through the generator/critic double-pass. *(Signature taxonomy, trust layer.)*

7. **Every proposed change** — mechanical or semantic — runs through the differential/property-based
   equivalence layer before it counts as verified. *(Trust and verification layer.)*

8. **Before any new dependency version lands**, the supply-chain provenance gate checks it against advisory and
   provenance sources. *(Supply-chain provenance gate.)*

9. **The decomposed trust score** is attached to the change as structured MCP tool output, so any calling agent
   or dashboard can parse and act on the components programmatically.

10. **Output is delivered**: a single urgent PR for critical CVEs, a sharded set of small PRs for a large
    confirmed "sync" (mirroring Google's large-scale-change infrastructure), a daily low-noise batch for
    mechanical fixes, or a weekly digest for everything needing human review — via the GitHub App, with the
    trust breakdown attached as a PR comment.

11. **Any human decision made along the way** — a pin, an exception, a sync-vs-shift choice — is written back
    into `resync.toml`, so the same situation is never re-litigated.

## Sequence at a glance

```
agent writes code ──▶ MCP gate check ──▶ [pass] continue
                                      └─▶ [fail] structured feedback to agent

scheduled sweep ──▶ knowledge retrieval ──▶ taxonomy classification ──▶ Impact Map
                                                                          │
                                                    ┌─────────────────────┼─────────────────────┐
                                                    ▼                     ▼                     ▼
                                             matches precedent      persisted policy      elicit via MCP
                                                    └─────────────────────┴─────────────────────┘
                                                                          ▼
                                                       mechanical (ast-grep) or semantic (local LLM) patch
                                                                          ▼
                                                        differential/property-based equivalence check
                                                                          ▼
                                                          supply-chain provenance gate (new versions only)
                                                                          ▼
                                                              decomposed trust score attached
                                                                          ▼
                                                     sharded/tiered PR delivery ──▶ resync.toml updated
```
