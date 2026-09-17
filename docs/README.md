# Documentation index

Start with `../README.md` for the project summary, then read in this order for full context:

1. **[`PRD.md`](PRD.md)** — the *what and why*: problem, target users, goals and success criteria,
   requirements, explicit scope boundaries. Start here if you're asking "should this exist" rather than
   "how does this work."
2. **[`architecture.md`](architecture.md)** (aliased as [`design.md`](design.md)) — the complete system
   design: the problem, design principles, every component, the build-priority table.
3. **[`workflow.md`](workflow.md)** — the end-to-end runtime flow, one fix from an agent's first keystroke to
   a merged PR.
4. **[`implementation-plan.md`](implementation-plan.md)** — the complete phased build plan, Phase 0 through
   Phase 9: foundation through knowledge layer, patch layer, verification, the MCP server, delivery, scaling,
   and release — with exit criteria per phase and the honest, precise status of each, not rounded up.
5. **[`testing-strategy.md`](testing-strategy.md)** — how each layer is tested, and why the verification layer
   is held to a higher bar than the rest of the codebase.
6. **[`release-plan.md`](release-plan.md)** — versioning, PyPI Trusted Publishing, and the pre-release and
   launch checklists.
7. **[`ui-design.md`](ui-design.md)** — the three surfaces a human actually looks at, and the design
   principles behind each.
8. **[`research-foundations.md`](research-foundations.md)** — the retrieval, verification, and local-execution
   research every architectural choice traces back to.
9. **[`competitive-landscape.md`](competitive-landscape.md)** — every existing tool and research prototype
   reviewed, and exactly what Resync does differently from each.
10. **[`tech-stack.md`](tech-stack.md)** — the full dependency manifest, including the Kùzu maintenance finding
    and the reasoning behind every package choice.
11. **[`multi-language-adapters.md`](multi-language-adapters.md)** — the adapter interface and each language's
    concrete implementation plan.
12. **[`adr/`](adr/)** — Architecture Decision Records for individual, significant decisions. Start with
    `adr/0000-template.md` if you're adding a new one.

See also **[`../AGENTS.md`](../AGENTS.md)** at the repo root — instructions specifically for AI coding agents
working in this codebase, including the single most important convention in the project (verify against a
real library or binary before writing code that calls it) and the list of tests that intentionally document
known limitations and should not be "fixed" by loosening their assertions.

If a decision in `architecture.md` seems under-justified, check whether there's an ADR for it before assuming
it wasn't considered — the ADRs exist specifically to carry the "why," including alternatives that were
reviewed and rejected.
