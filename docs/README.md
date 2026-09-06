# Documentation index

Start with `../README.md` for the project summary, then read in this order for full context:

1. **[`architecture.md`](architecture.md)** — the complete system design: the problem, design principles,
   every component, the build-priority table.
2. **[`workflow.md`](workflow.md)** — the end-to-end runtime flow, one fix from an agent's first keystroke to
   a merged PR.
3. **[`implementation-plan.md`](implementation-plan.md)** — the phased build plan from the current scaffold to
   a demoable v0.1.0, with exit criteria per phase.
4. **[`testing-strategy.md`](testing-strategy.md)** — how each layer is tested, and why the verification layer
   is held to a higher bar than the rest of the codebase.
5. **[`release-plan.md`](release-plan.md)** — versioning, PyPI Trusted Publishing, and the pre-release and
   launch checklists.
6. **[`ui-design.md`](ui-design.md)** — the three surfaces a human actually looks at, and the design
   principles behind each.
7. **[`research-foundations.md`](research-foundations.md)** — the retrieval, verification, and local-execution
   research every architectural choice traces back to.
8. **[`competitive-landscape.md`](competitive-landscape.md)** — every existing tool and research prototype
   reviewed, and exactly what Resync does differently from each.
9. **[`tech-stack.md`](tech-stack.md)** — the full dependency manifest, including the Kùzu maintenance finding
   and the reasoning behind every package choice.
10. **[`multi-language-adapters.md`](multi-language-adapters.md)** — the adapter interface and each language's
    concrete implementation plan.
11. **[`adr/`](adr/)** — Architecture Decision Records for individual, significant decisions. Start with
    `adr/0000-template.md` if you're adding a new one.

If a decision in `architecture.md` seems under-justified, check whether there's an ADR for it before assuming
it wasn't considered — the ADRs exist specifically to carry the "why," including alternatives that were
reviewed and rejected.
