# `scripts/`

Operational, installation, and maintenance scripts for Resync. All scripts are designed for cross-platform execution on both Windows and Linux/macOS.

---

## 1. Automated Single-Launch Installers

Both installers provide an end-to-end, multi-stage installation workflow with lightweight terminal animations, interactive profile choices, complete MCP server auto-registration, model cache pre-warming, and system health verification.

### [`install.exe`](install.exe) (Source: [`installer.c`](installer.c)) — Windows Native Executable Installer
Automated, standalone, zero-dependency native executable for Windows.
- **Background Tooling**: Automatically provisions `uv`, native `ast-grep`, and standalone CPython 3.12 (if system Python < 3.11).
- **Interactive CLI Workflow & Lightweight Spinners**: Features smooth non-blocking console spinner animation during long-running tasks and an interactive menu when launched directly:
  1. *Standard AI Agent MCP Server* (Recommended — lightweight, fast ONNX model, zero-torch)
  2. *Full Developer & Research Environment* (includes pytest, hypothesis, mypy, ruff, verify tools)
  3. *Global Tool Installation* (installs Resync into user PATH for system-wide usage)
- **Model Cache Pre-Warming & Knowledge Seeding**: Pre-downloads the fast quantized embedding model (`nomic-ai/nomic-embed-text-v1.5-Q`) and seeds `.resync/knowledge.lancedb` via `resync seed --force` for immediate offline readiness.
- **Complete MCP Server Setup**: Auto-detects and registers active AI coding agents (Google Antigravity global & workspace, Claude Code, Claude Desktop, Cursor, VS Code, Zed, Windsurf) and configures team project templates (`resync mcp-config-auto --all`).
- **Automated Health Check**: Concludes by running `resync doctor` to verify that all 9 subsystems report `PASS`.
- **Compilation**: Can be rebuilt with `gcc -O2 -static -Wall scripts/installer.c -o scripts/install.exe` or `make installer`.
- **Usage**:
  ```cmd
  # Interactive single-click launch:
  .\scripts\install.exe

  # Unattended CI / automated setup:
  .\scripts\install.exe -y

  # Local dev environment with test suites:
  .\scripts\install.exe --local --dev

  # Targeted client setup:
  .\scripts\install.exe --client cursor
  ```

### [`install.sh`](install.sh) — Linux / macOS POSIX Installer
Automated, bare-metal installation script for POSIX environments (Bash / Zsh / sh).
- **Parity with Windows Installer**: Implements identical multi-stage setup, interactive profile prompt, non-blocking bash spinner, embedding model pre-warming, knowledge base seeding, project template configuration, and `resync doctor` diagnostic check.
- **Usage**:
  ```bash
  # Remote one-liner:
  curl -fsSL https://raw.githubusercontent.com/priyanshu-ogdev/Resync/main/scripts/install.sh | bash

  # Interactive local run:
  ./scripts/install.sh

  # Unattended automated run:
  ./scripts/install.sh -y
  ```

---

## 2. Environment Diagnostics

### [`verify_install.py`](verify_install.py) — Environment Health Check
Cross-platform diagnostic tool to verify that all prerequisites, binaries, and dependencies are satisfied:
- Verifies Python version (`>=3.11`).
- Verifies `uv` package manager and `ast-grep` native binary availability on `PATH`.
- Verifies `resync` CLI command accessibility.
- Validates zero-torch hygiene and confirms required packages (`pydantic`, `mcp`, `griffe`, `fastembed`, `lancedb`).
- Inspects configuration files for detected coding agents (Google Antigravity, Claude Desktop, Claude Code, Cursor, VS Code, Zed).
- Executes live MCP server protocol handshake test over stdio.
- **Usage**:
  ```bash
  uv run python scripts/verify_install.py
  ```

---

## 3. Maintenance

### [`clean.py`](clean.py) — Cross-Platform Cache Cleaner
Safely cleans build artifacts, test caches, and bytecode without requiring Unix `rm -rf`:
- Removes `__pycache__`, `.pytest_cache`, `.hypothesis`, `.mypy_cache`, `.ruff_cache`, `dist/`, `build/`, `*.egg-info`.
- Safely skips `.git` and `.venv`.
- **Usage**:
  ```bash
  uv run python scripts/clean.py [--quiet] [--include-data]
  ```
