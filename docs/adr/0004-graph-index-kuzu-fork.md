# ADR 0004: Use the actively-maintained Kùzu fork, not the original archived project

**Status:** accepted

## Context

The call/import graph underpinning the knowledge layer and the Impact Map needs an embedded, Cypher-compatible
graph database — no separate server process to run, matching the project's local-first, low-resource posture.
The original `kuzudb/kuzu` project fit this requirement, but was archived in October 2025 after Apple acquired
the company behind it (Kùzu Inc.). Package health trackers now flag the original as inactive/deprecated, with
no commits in six or more months at time of review.

## Decision

Depend on the actively-maintained community fork (`Vela-Engineering/kuzu`, maintained by Vela Partners) rather
than the archived original. The fork preserves the same Cypher interface, embedded architecture, and language
bindings, and adds concurrent multi-writer support — relevant here since multiple language adapters may write
knowledge records into the graph concurrently, which the original single-writer constraint would have
serialized. Before pinning a version in `pyproject.toml`, confirm the exact installation source from the
fork's own documentation rather than assuming it is published under the original `kuzu` PyPI name — this was
not independently verifiable at review time.

## Alternatives considered

- **Stay on the original `kuzudb/kuzu`** — rejected: actively deprecated, a real risk for a "final" dependency
  choice, regardless of how well it fit the technical requirements otherwise.
- **Memgraph** — a viable fallback with a longer independent track record and active development, at the cost
  of running a lightweight server process instead of a pure in-process embed. Recommended if a contributor
  would rather not depend on a single company's fork of an orphaned project.
- **Neo4j** — rejected as the primary choice for this project's scale: requires dedicated server infrastructure
  and GPLv3/commercial licensing, disproportionate for an embedded, hackathon-to-production-scale tool.

## Consequences

This introduces dependency risk on a smaller, single-company-maintained fork rather than a project with broad
institutional backing. Revisit this decision if the fork's own maintenance signals change, or if Memgraph
becomes the more pragmatic default once the project needs true multi-tenant, always-on server deployment
regardless of the "embedded" preference.

## References

- Kùzu archival notice (October 2025, following the Apple acquisition of Kùzu Inc.) and subsequent package
  health assessments marking the original as inactive/deprecated.
- `Vela-Engineering/kuzu` fork documentation.
