# `examples/`

Example configurations and integration templates for downstream projects adopting Resync.

## Contents

- **`resync.toml`** — a minimal starting configuration. Copy it to your project's repository root and customize; see [`docs/architecture.md#resynctoml-the-compatibility-contract`](../docs/architecture.md) for the full field reference, and the repository root [`resync.toml`](../resync.toml) for a fully-populated example with pins, exceptions, and policies.
- **`mcp-configs/`** — verified, ready-to-use MCP configuration files:
  - [`claude-desktop.json`](mcp-configs/claude-desktop.json): For Claude Desktop (`claude_desktop_config.json`).
  - [`claude-code.json`](mcp-configs/claude-code.json): For Claude Code (`.mcp.json`).
  - [`cursor.json`](mcp-configs/cursor.json): For Cursor (`.cursor/mcp.json`).
  - [`vscode.json`](mcp-configs/vscode.json): For VS Code / GitHub Copilot (`.vscode/mcp.json`).
  - [`antigravity.json`](mcp-configs/antigravity.json): For Google Antigravity.
- **`github-actions/`** — CI/CD workflow templates:
  - [`resync-check.yml`](github-actions/resync-check.yml): GitHub Actions workflow to run `resync check` on PRs and commits.

