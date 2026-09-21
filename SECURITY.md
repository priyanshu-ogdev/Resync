# Security Policy

Resync's own purpose is closing supply-chain and correctness gaps in dependency tooling, so it holds itself to
the same standard it enforces on the codebases it upgrades.

## Reporting a vulnerability

Please do not open a public GitHub issue for a suspected security vulnerability. Instead:

1. Email the maintainers at **security@[project-domain]** (replace with the real address before release) with
   a description of the issue, steps to reproduce, and its potential impact.
2. You should receive an acknowledgment within **3 business days**.
3. We aim to provide an initial assessment within **10 business days**, and will keep you informed of progress
   toward a fix.
4. Please allow us to publish a fix before any public disclosure. We're happy to credit reporters in the
   release notes unless you'd prefer otherwise.

## Supported versions

While the project is pre-1.0, only the latest released minor version receives security fixes. This will be
formalized into a support-window table once 1.0 ships.

## Scope notes specific to this project

Resync's own design surface includes a few areas that deserve extra scrutiny from reporters:

- **The real-time MCP gate** (`verify_package`, `check_symbol_exists`) — any bypass that lets an unverified or
  advisory-flagged package pass the check is a high-severity issue.
- **`resync.toml` pin/exception enforcement** — per `docs/architecture.md#decision-3-deterministic-first-patching`, these
  checks must be enforced in tool functions, not merely advisory in a prompt; any path that lets a model-drafted
  patch bypass a pin is a design-breaking bug, not a minor one.
- **The supply-chain provenance gate** (OSV.dev / GitHub Advisory / Sigstore checks) — false negatives here
  (a malicious or yanked package passing verification) are treated as security issues, not correctness bugs.
- **The sandboxed execution environment** — since it wraps agent-driven code execution, a sandbox escape is
  always in scope regardless of which underlying sandbox implementation is in use.

## Dependencies

This project depends on `sigstore` and the OSV.dev / GitHub Advisory Database APIs for its own supply-chain
checks. If a reported issue traces back to one of those upstream services or libraries rather than Resync's
own code, we'll still coordinate on responsible disclosure and help route it appropriately.
