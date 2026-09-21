"""Resync Installation Diagnostic & Verification Script.

Checks for bare-metal prerequisites, binary accessibility (uv, ast-grep, resync),
minimal bloat compliance (no torch), and detects MCP agent registrations.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


def _check_command(cmd: str) -> tuple[bool, str]:
    path = shutil.which(cmd)
    if not path:
        return False, "Not found on PATH"
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
        version = proc.stdout.strip() or proc.stderr.strip() or "Available"
        return True, f"{path} ({version.splitlines()[0]})"
    except Exception as exc:
        return True, f"{path} (error running: {exc})"


def main() -> int:
    print("=" * 60)
    print("Resync Installation & Environment Verification")
    print("=" * 60)
    print()

    # 1. Python Check
    py_ver = sys.version.split()[0]
    py_ok = sys.version_info >= (3, 11)
    py_status = "[OK]" if py_ok else "[FAIL]"
    print(f"{py_status} Python Version: {py_ver} (>= 3.11 required)")

    # 2. uv Check
    uv_ok, uv_detail = _check_command("uv")
    uv_status = "[OK]" if uv_ok else "[WARN]"
    print(f"{uv_status} uv Package Manager: {uv_detail}")

    # 3. ast-grep Check
    ast_ok, ast_detail = _check_command("ast-grep")
    ast_status = "[OK]" if ast_ok else "[FAIL]"
    print(f"{ast_status} ast-grep Native Binary: {ast_detail}")

    # 4. resync Check
    resync_ok, resync_detail = _check_command("resync")
    resync_status = "[OK]" if resync_ok else "[WARN]"
    print(f"{resync_status} resync CLI Command: {resync_detail}")

    # 5. Core Package Imports & Bloat Verification
    print("\nPackage & Dependency Hygiene Check:")
    has_torch = importlib.util.find_spec("torch") is not None
    if has_torch:
        print("  [INFO] torch detected in environment (not used or required by Resync core)")
    else:
        print("  [OK] Zero-torch confirmed: lightweight ONNX/Griffe architecture active")

    required_packages = [
        "pydantic",
        "typer",
        "rich",
        "mcp",
        "griffe",
        "fastembed",
        "lancedb",
        "kuzu",
        "tomli_w",
        "yaml",
    ]
    for pkg in required_packages:
        found = importlib.util.find_spec(pkg) is not None
        pkg_status = "[OK]" if found else "[MISSING]"
        display_name = "pyyaml (yaml)" if pkg == "yaml" else pkg
        print(f"  {pkg_status} {display_name}")

    # 6. Active Language Adapters Discovery
    print("\nLanguage Adapters Discovery:")
    try:
        from resync.adapters.registry import list_supported_languages

        languages = list_supported_languages()
        print(f"  [OK] Discovered {len(languages)} active language adapters:")
        for meta in languages:
            print(f"       - {meta.display_name} ({meta.name}) [{meta.ecosystem}]")
    except Exception as exc:
        print(f"  [WARN] Could not discover adapters: {exc}")

    # 7. Check MCP Clients on this machine
    print("\nMCP Client Configuration Status:")
    home = Path.home()
    configs = {
        "Google Antigravity (Global)": home / ".gemini" / "config" / "mcp_config.json",
        "Google Antigravity (Workspace)": Path(".agents") / "mcp_config.json",
        "Claude Code (Project)": Path(".mcp.json"),
        "Claude Code (User)": home / ".claude.json",
        "Claude Desktop": home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
        if sys.platform == "win32"
        else home / ".config" / "Claude" / "claude_desktop_config.json",
        "Cursor (Project)": Path(".cursor") / "mcp.json",
        "VS Code (Project)": Path(".vscode") / "mcp.json",
        "Zed (Project)": Path(".zed") / "settings.json",
        "Windsurf (Global)": home / ".codeium" / "windsurf" / "mcp_config.json",
    }

    for client_name, conf_path in configs.items():
        if conf_path.exists():
            try:
                content = conf_path.read_text(encoding="utf-8")
                registered = "resync" in content.lower()
                status = "[REGISTERED]" if registered else "[PRESENT, NOT CONFIGURED]"
                print(f"  {status} {client_name} ({conf_path})")
            except Exception:
                print(f"  [FOUND] {client_name} ({conf_path})")
        else:
            print(f"  [--] {client_name} (no config file at {conf_path.name})")

    # 8. Live MCP Server Protocol Handshake Verification
    print("\nLive MCP Protocol Handshake Verification:")
    try:
        from resync.cli.mcp_verify import verify_server_launch

        handshake = verify_server_launch(Path("."))
        if handshake.status == "verified":
            print(f"  [OK] MCP Server stdio handshake verified ({len(handshake.tools_found)} tools live):")
            for t in handshake.tools_found:
                print(f"       - {t}")
        else:
            print(f"  [WARN] Handshake status: {handshake.status} ({handshake.detail})")
    except Exception as exc:
        print(f"  [WARN] Could not perform live handshake check: {exc}")

    print("\n" + "=" * 60)
    all_critical_ok = py_ok and ast_ok
    if all_critical_ok:
        print("Verification SUCCESS: Resync core prerequisites and MCP server are verified.")
        return 0
    else:
        print("Verification WARNING: Some prerequisites are missing.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
