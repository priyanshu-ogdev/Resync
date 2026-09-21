#!/usr/bin/env bash
# Resync Installer for Linux & macOS
# Automates background provisioning of uv, Python 3.12, ast-grep, embedding models, and Resync MCP server.
#
# Usage:
#   ./installer/install.sh [--local] [--dev] [--client <name>] [--yes]
#   Remote one-liner:
#   curl -fsSL https://raw.githubusercontent.com/priyanshu-ogdev/Resync/main/installer/install.sh | bash

set -euo pipefail

LOCAL=0
GLOBAL=0
DEV=0
CLIENT=""
SKIP_MCP=0
NON_INTERACTIVE=0
ACTIVE_CHILD_PID=""
TEMP_LOG="/tmp/resync_install_$$.log"

print_header() {
    echo ""
    echo -e "  \033[1;36m╭────────────────────────────────────────────────────────────────────────╮\033[0m"
    echo -e "  \033[1;36m│\033[0m   RESYNC  ──  AI-Native Dependency & API Compatibility Engine          \033[1;36m│\033[0m"
    echo -e "  \033[1;36m│\033[0m   Stateless MCP Server  •  Zero-Torch  •  FastEmbed Quantized ONNX     \033[1;36m│\033[0m"
    echo -e "  \033[1;36m╰────────────────────────────────────────────────────────────────────────╯\033[0m"
    echo ""
}

print_preflight() {
    local in_repo="$1"
    local scope="Global user CLI tool"
    [ "$in_repo" -eq 1 ] && scope="Local repository (.venv)"
    echo -e "  \033[2mPre-flight Environment:\033[0m"
    echo -e "    \033[2m• Platform:       $(uname -s) $(uname -m)\033[0m"
    echo -e "    \033[2m• Target Scope:   $scope\033[0m"
    echo -e "    \033[2m• Architecture:   Stateless MCP Core (2026-07-28), Zero-Torch\033[0m"
    echo ""
}

print_completion_card() {
    local resync_desc="$1"
    echo ""
    echo -e "  \033[1;32m╭────────────────────────────────────────────────────────────────────────╮\033[0m"
    echo -e "  \033[1;32m│  ✔  Resync MCP Server Successfully Installed & Ready!                  │\033[0m"
    echo -e "  \033[1;32m├────────────────────────────────────────────────────────────────────────┤\033[0m"
    printf "  │  Resync Engine: %-54.54s │\n" "$resync_desc"
    echo -e "  │  MCP Server:    stdio (resync serve) | streamable-http (port 8787)     │"
    echo -e "  │  MCP Tools (5): verify_package, check_symbol_exists, explain_change... │"
    echo -e "  │  Dashboard:     http://127.0.0.1:8787/dashboard (diffs & trust scores) │"
    echo -e "  │  Agents Linked: Google Antigravity, Claude Code, Cursor, VS Code, Zed  │"
    echo -e "  │  Knowledge:     14 verified records seeded (.resync/knowledge.lancedb) │"
    echo -e "  │  Embedding:     nomic-embed-text-v1.5-Q (130 MB quantized ONNX)        │"
    echo -e "  │  Architecture:  Stateless MCP 2026-07-28, zero-torch, 7 adapters      │"
    echo -e "  \033[1;32m├────────────────────────────────────────────────────────────────────────┤\033[0m"
    echo -e "  │  Quick Commands:                                                       │"
    echo -e "  │    resync run --explain   Complete compatibility & correction run      │"
    echo -e "  │    resync check --explain Static scan with decomposed trust scores     │"
    echo -e "  │    resync explain <tgt>   Explain change with 4-tier trust score       │"
    echo -e "  │    resync serve           Start live MCP server & review dashboard     │"
    echo -e "  │    resync doctor          Inspect complete subsystem health matrix     │"
    echo -e "  \033[1;32m╰────────────────────────────────────────────────────────────────────────╯\033[0m"
    echo ""
}

show_help() {
    print_header
    cat <<EOF
Usage: ./installer/install.sh [OPTIONS]

Options:
  --local, -l        Install into local repository virtual environment (.venv)
  --global, -g       Install as a global user CLI tool
  --dev, -d          Include developer & test suites (mypy, ruff, pytest)
  --client <name>    Auto-configure for a specific client (antigravity, claude-code, cursor, vscode, claude-desktop, windsurf, zed)
  --yes, -y          Non-interactive execution (accept all defaults)
  --skip-mcp         Skip MCP client configuration
  -h, --help         Show this help message

Examples:
  ./installer/install.sh                     # Interactive single-launch install & full MCP setup
  ./installer/install.sh -y                  # Unattended setup (CI / automated)
  ./installer/install.sh --local --dev       # Local dev setup with test suites
  ./installer/install.sh --client cursor     # Install and configure for Cursor

EOF
    exit 0
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --local|-l) LOCAL=1; shift ;;
        --global|-g) GLOBAL=1; shift ;;
        --dev|-d) DEV=1; shift ;;
        --client) CLIENT="${2:-}"; shift 2 ;;
        --yes|-y) NON_INTERACTIVE=1; shift ;;
        --skip-mcp) SKIP_MCP=1; shift ;;
        -h|--help) show_help ;;
        *) echo "Unknown option: $1"; show_help ;;
    esac
done

step() { echo -e "  \033[1;36mℹ\033[0m $*"; }
success() { echo -e "  \033[1;32m✔\033[0m $*"; }
warn() { echo -e "  \033[1;33m▲\033[0m $*"; }
err() { echo -e "  \033[1;31m✖\033[0m $*" >&2; }

stage() {
    local num="$1"
    local total="$2"
    local title="$3"
    echo ""
    echo -e "  \033[1;36m◆ Stage $num/$total:\033[0m $title"
}

cleanup_terminal() {
    if [ -n "${ACTIVE_CHILD_PID:-}" ] && kill -0 "$ACTIVE_CHILD_PID" 2>/dev/null; then
        kill -TERM "$ACTIVE_CHILD_PID" 2>/dev/null || kill -KILL "$ACTIVE_CHILD_PID" 2>/dev/null || true
    fi
    rm -f "$TEMP_LOG" 2>/dev/null || true
    printf "\033[?25h" 2>/dev/null || true
}
trap cleanup_terminal EXIT INT TERM

run_with_spinner() {
    local label="$1"
    shift

    if [ ! -t 1 ]; then
        step "$label..."
        "$@"
        return $?
    fi

    printf "\033[?25l" 2>/dev/null || true

    local start_time=$SECONDS
    "$@" >"$TEMP_LOG" 2>&1 &
    ACTIVE_CHILD_PID=$!
    local spin=('◐' '◓' '◑' '◒')
    local i=0

    while kill -0 "$ACTIVE_CHILD_PID" 2>/dev/null; do
        local elapsed=$(( SECONDS - start_time ))
        i=$(( (i+1) % 4 ))
        printf "\r  \033[1;36m%s\033[0m %s... (%ds)   " "${spin[$i]}" "$label" "$elapsed"
        sleep 0.08
    done

    wait "$ACTIVE_CHILD_PID"
    local exit_code=$?
    ACTIVE_CHILD_PID=""
    local total_elapsed=$(( SECONDS - start_time ))

    printf "\033[?25h" 2>/dev/null || true

    if [ "$exit_code" -eq 0 ]; then
        printf "\r  \033[1;32m✔\033[0m %s \033[2m[%ds]\033[0m                          \n" "$label" "$total_elapsed"
        rm -f "$TEMP_LOG" 2>/dev/null || true
    else
        printf "\r  \033[1;31m✖\033[0m %s (exit code %d) \033[2m[%ds]\033[0m          \n" "$label" "$exit_code" "$total_elapsed"
        if [ -s "$TEMP_LOG" ]; then
            head -n 15 "$TEMP_LOG" | sed 's/^/    /'
            rm -f "$TEMP_LOG" 2>/dev/null || true
        fi
    fi
    return "$exit_code"
}

persist_linux_path() {
    local target_dir="$HOME/.local/bin"
    local export_line="export PATH=\"$target_dir:\$PATH\""
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        if [ -f "$rc" ]; then
            if ! grep -qsF "$target_dir" "$rc"; then
                printf "\n# Resync & uv user binaries\n%s\n" "$export_line" >> "$rc"
            fi
        fi
    done
}

print_header

REPO_ROOT=""
if [ -f "pyproject.toml" ]; then
    REPO_ROOT="$(pwd)"
elif [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/../pyproject.toml" ]; then
    REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

in_repo_flag=0
[ -n "$REPO_ROOT" ] && in_repo_flag=1
print_preflight "$in_repo_flag"

# Interactive Menu if in terminal without flags
if [ "$NON_INTERACTIVE" -eq 0 ] && [ -t 0 ] && [ "$LOCAL" -eq 0 ] && [ "$GLOBAL" -eq 0 ] && [ "$DEV" -eq 0 ] && [ -z "$CLIENT" ]; then
    echo "  Select Installation Profile:"
    echo ""
    echo -e "    \033[1;32m[1] Standard AI Agent MCP Server (Recommended)\033[0m"
    echo "        Fast, lightweight, zero-torch profile. Configures MCP server, seeds"
    echo "        knowledge store, pre-warms quantized model, and auto-links AI agents."
    echo ""
    echo -e "    \033[1;36m[2] Full Developer & Research Environment\033[0m"
    echo "        Includes pytest, hypothesis, mypy, ruff, and test fixtures."
    echo ""
    echo -e "    \033[1;33m[3] Global Tool Installation\033[0m"
    echo "        Installs Resync CLI globally into user PATH rather than repo .venv."
    echo ""
    echo "    [4] Exit"
    echo ""
    read -r -p "  Enter selection [1-4] (default: 1): " choice || choice=""
    case "$choice" in
        2) DEV=1; LOCAL=1 ;;
        3) GLOBAL=1 ;;
        4) echo -e "\n  Installation cancelled.\n"; exit 0 ;;
        *) LOCAL=1 ;;
    esac
    echo ""
fi

# 1. Ensure ~/.local/bin is in PATH for current shell and persistent profile
USER_LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$USER_LOCAL_BIN" 2>/dev/null || true
case ":$PATH:" in
    *":$USER_LOCAL_BIN:"*) ;;
    *) export PATH="$USER_LOCAL_BIN:$PATH" ;;
esac
persist_linux_path

# STAGE 1: Runtime & Tooling
stage 1 5 "Provisioning Core Runtime & Tooling (uv, Python 3.12, ast-grep)"

UV_BIN=""
if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
elif [ -x "$USER_LOCAL_BIN/uv" ]; then
    UV_BIN="$USER_LOCAL_BIN/uv"
elif [ -x "$HOME/.cargo/bin/uv" ]; then
    UV_BIN="$HOME/.cargo/bin/uv"
fi

if [ -z "$UV_BIN" ]; then
    if command -v curl >/dev/null 2>&1; then
        run_with_spinner "Downloading Astral uv via curl" sh -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
    elif command -v wget >/dev/null 2>&1; then
        run_with_spinner "Downloading Astral uv via wget" sh -c "wget -qO- https://astral.sh/uv/install.sh | sh"
    else
        err "Neither curl nor wget found. Please install curl or wget first."
        exit 1
    fi
    export PATH="$USER_LOCAL_BIN:$PATH"
    if [ -x "$USER_LOCAL_BIN/uv" ]; then
        UV_BIN="$USER_LOCAL_BIN/uv"
    elif command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"
    else
        err "uv installation completed but binary could not be found."
        exit 1
    fi
    success "Astral uv package manager installed."
else
    success "Astral uv package manager available."
fi

if "$UV_BIN" python find ">=3.11" >/dev/null 2>&1; then
    success "Compatible Python environment (>= 3.11) verified."
else
    run_with_spinner "Installing standalone CPython 3.12 via uv" "$UV_BIN" python install 3.12
    success "Compatible Python environment (>= 3.11) verified."
fi

if ! command -v ast-grep >/dev/null 2>&1; then
    run_with_spinner "Installing native ast-grep AST engine" "$UV_BIN" tool install ast-grep-cli --force
    export PATH="$USER_LOCAL_BIN:$PATH"
    success "ast-grep native binary verified."
else
    success "ast-grep native binary verified."
fi

persist_linux_path

install_resync_shim() {
    local target_bin="$1"
    local shim_path="$USER_LOCAL_BIN/resync"
    mkdir -p "$USER_LOCAL_BIN" 2>/dev/null || true
    cat <<EOF > "$shim_path"
#!/usr/bin/env bash
exec "$target_bin" "\$@"
EOF
    chmod +x "$shim_path"
}

# STAGE 2: Resync Engine & Libraries
stage 2 5 "Building Resync Compatibility Engine & Libraries"

run_resync() {
    if [ "$LOCAL" -eq 1 ] || { [ -n "$REPO_ROOT" ] && [ "$GLOBAL" -eq 0 ]; }; then
        if [ -x "$REPO_ROOT/.venv/bin/resync" ]; then
            "$REPO_ROOT/.venv/bin/resync" "$@"
        elif command -v resync >/dev/null 2>&1; then
            resync "$@"
        else
            "$UV_BIN" run resync "$@"
        fi
    elif command -v resync >/dev/null 2>&1; then
        resync "$@"
    else
        "$UV_BIN" run resync "$@"
    fi
}

if [ "$LOCAL" -eq 1 ] || { [ -n "$REPO_ROOT" ] && [ "$GLOBAL" -eq 0 ]; }; then
    cd "$REPO_ROOT"
    if [ "$DEV" -eq 1 ]; then
        run_with_spinner "Syncing local environment with developer & verification suites" \
            "$UV_BIN" sync --extra server --extra cli --group dev --group verify
    else
        run_with_spinner "Syncing lightweight production profile (server + cli, zero-torch)" \
            "$UV_BIN" sync --extra server --extra cli
    fi
    install_resync_shim "$REPO_ROOT/.venv/bin/resync"
    RESYNC_CMD="resync"
else
    if [ -n "$REPO_ROOT" ]; then
        run_with_spinner "Installing Resync globally in editable mode" \
            "$UV_BIN" tool install --editable "$REPO_ROOT" --extra server --extra cli --with ast-grep-cli --force
    else
        run_with_spinner "Installing Resync globally from package index" \
            "$UV_BIN" tool install "resync-mcp[server,cli]" --with ast-grep-cli --force
    fi
    RESYNC_CMD="resync"
fi

# Verify executable
if ! "$RESYNC_CMD" --help >/dev/null 2>&1; then
    if [ -x "$REPO_ROOT/.venv/bin/resync" ]; then
        RESYNC_CMD="$REPO_ROOT/.venv/bin/resync"
    else
        err "Resync executable verification failed."
        exit 1
    fi
fi
success "Resync CLI engine operational."

# STAGE 3: Model Cache Pre-Warming & Knowledge Store Seeding
stage 3 5 "Pre-Warming Embedding Model & Seeding Knowledge Store"

if [ -n "$REPO_ROOT" ] && [ ! -f "resync.toml" ] && [ ! -f "../resync.toml" ]; then
    run_with_spinner "Creating resync.toml configuration" run_resync init --yes --no-seed || true
fi

run_with_spinner "Seeding built-in verified records into LanceDB store" run_resync seed || true

configure_mcp_integrations() {
    if [ -n "$CLIENT" ]; then
        step "Configuring Resync MCP server for '$CLIENT'..."
        run_resync mcp-config "$CLIENT" --verify || warn "Could not verify '$CLIENT' end-to-end."
    elif [ -n "$REPO_ROOT" ]; then
        step "Auto-configuring active AI coding agents and project templates..."
        run_resync mcp-config-auto --all || warn "Auto-registration completed with warnings."
    else
        step "Auto-configuring active global AI coding agents..."
        run_resync mcp-config-auto || warn "Auto-registration completed with warnings."
    fi
}

# STAGE 4: AI Coding Agent MCP Auto-Configuration
if [ "$SKIP_MCP" -eq 0 ]; then
    stage 4 5 "Auto-Configuring AI Coding Agent MCP Integrations"
    configure_mcp_integrations
else
    step "Skipping MCP client configuration (--skip-mcp specified)."
fi

# STAGE 5: System Diagnostics & Health Verification
stage 5 5 "Running Comprehensive System Diagnostics (Doctor)"

run_resync doctor || true

if [ -f "tools/verify_install.py" ]; then
    if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
        "$REPO_ROOT/.venv/bin/python" tools/verify_install.py || true
    else
        python3 tools/verify_install.py || true
    fi
fi

print_completion_card "resync (native CLI on PATH)"
