# `cli/`

The offline-first command-line surface — see `docs/architecture.md#integration-surfaces`. `main.py` defines
three commands: `serve` (start the MCP server), `check` (run the real-time gate against an existing repo,
useful as a pre-commit/CI step outside of any agent), and `sync` (run one tier of the scheduled correction
sweep manually).
