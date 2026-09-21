# `tools/`

Internal developer utilities, diagnostics, and build sources for Resync.

---

## Utilities

### 1. `installer.c` — Source for Native Windows Installer
C source code for [`installer/install.exe`](../installer/install.exe).
- Zero external runtime dependencies; links statically against MSVCRT and Windows system libraries.
- Compiles with MinGW GCC:
  ```cmd
  gcc -O2 -static -Wall tools/installer.c -o installer/install.exe
  ```
  Or using `make`:
  ```bash
  make installer
  ```

### 2. `verify_install.py` — Installation & Environment Verification
Cross-platform diagnostic tool to verify that all prerequisites, binaries, and dependencies are satisfied:
- Verifies Python runtime version (`>=3.11`).
- Verifies `uv` package manager and `ast-grep` native binary availability on `PATH`.
- Verifies `resync` CLI command accessibility.
- Validates zero-torch hygiene and confirms required packages (`pydantic`, `mcp`, `griffe`, `fastembed`, `lancedb`, `kuzu`).
- Verifies registration of all 7 polyglot language adapters.
- Inspects configuration files for detected coding agents (Google Antigravity, Claude Code, Cursor, VS Code, Zed).
- Executes live MCP server protocol handshake test over stdio (5 production tools).
- **Usage**:
  ```bash
  uv run python tools/verify_install.py
  ```

### 3. `clean.py` — Repository Cache Cleaner
Safely cleans build artifacts, test caches, temporary files, and bytecode without requiring Unix `rm -rf`:
- Removes `__pycache__`, `.pytest_cache`, `.hypothesis`, `.mypy_cache`, `.ruff_cache`, `dist/`, `build/`, `*.egg-info`.
- Safely preserves `.git` and `.venv`.
- **Usage**:
  ```bash
  uv run python tools/clean.py [--quiet] [--include-data]
  ```
