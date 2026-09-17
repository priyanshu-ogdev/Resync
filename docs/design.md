# Design document

This file is a deliberate alias, not a duplicate: the actual design document is
**[`architecture.md`](architecture.md)**.

Why an alias instead of a rename: `architecture.md` is cross-referenced by name from every ADR in `adr/`,
from `implementation-plan.md`, `testing-strategy.md`, `ui-design.md`, and from module-level docstrings and
`README.md` files throughout `src/resync/`. Renaming it would silently break every one of those references
for a purely cosmetic gain. This file exists so that "design.md" — a name some conventions and some readers
expect by default — still resolves to the right place.

See also `PRD.md` (the *what and why*, as distinct from this document's *how*) and `workflow.md` (the
runtime flow through the design described here).
