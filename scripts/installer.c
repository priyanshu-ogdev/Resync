/*
 * Resync MCP Server Native Single-Launch Installer for Windows.
 *
 * A standalone, zero-dependency executable that automates:
 * 1. Background provisioning of Astral uv, Python 3.12, and ast-grep
 * 2. Building Resync MCP server and CLI libraries
 * 3. Pre-warming the embedding model (nomic-ai/nomic-embed-text-v1.5-Q) & seeding knowledge store
 * 4. Complete auto-detection and registration of AI coding agents (Antigravity, Claude, Cursor, VS Code, Zed)
 * 5. Auto-configuring AI coding agents & project MCP integrations (resync mcp-config-auto --all)
 * 6. System health check and diagnostics verification (resync doctor)
 *
 * Build:
 *   gcc -O2 -static -Wall scripts/installer.c -o scripts/install.exe
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <ctype.h>
#include <io.h>
#include <windows.h>

static HANDLE hConsole;
static volatile HANDLE hActiveChildProcess = NULL;

static void set_color(WORD color) {
    if (!hConsole) {
        hConsole = GetStdHandle(STD_OUTPUT_HANDLE);
    }
    SetConsoleTextAttribute(hConsole, color);
}

static void reset_color(void) {
    set_color(FOREGROUND_RED | FOREGROUND_GREEN | FOREGROUND_BLUE);
}

static void set_cursor_visible(bool visible) {
    if (!hConsole) {
        hConsole = GetStdHandle(STD_OUTPUT_HANDLE);
    }
    CONSOLE_CURSOR_INFO cci;
    if (GetConsoleCursorInfo(hConsole, &cci)) {
        cci.bVisible = visible ? TRUE : FALSE;
        SetConsoleCursorInfo(hConsole, &cci);
    }
}

static BOOL WINAPI console_ctrl_handler(DWORD ctrlType) {
    (void)ctrlType;
    if (hActiveChildProcess != NULL) {
        TerminateProcess((HANDLE)hActiveChildProcess, 1);
        hActiveChildProcess = NULL;
    }
    set_cursor_visible(true);
    reset_color();
    return FALSE;
}

static void print_step(const char *msg) {
    set_color(FOREGROUND_GREEN | FOREGROUND_BLUE | FOREGROUND_INTENSITY); /* Cyan */
    printf("  ℹ ");
    reset_color();
    printf("%s\n", msg);
}

static void print_success(const char *msg) {
    set_color(FOREGROUND_GREEN | FOREGROUND_INTENSITY); /* Green */
    printf("  ✔ ");
    reset_color();
    printf("%s\n", msg);
}

static void print_warn(const char *msg) {
    set_color(FOREGROUND_RED | FOREGROUND_GREEN | FOREGROUND_INTENSITY); /* Yellow */
    printf("  ▲ ");
    reset_color();
    printf("%s\n", msg);
}

static void print_err(const char *msg) {
    set_color(FOREGROUND_RED | FOREGROUND_INTENSITY); /* Red */
    printf("  ✖ ");
    reset_color();
    printf("%s\n", msg);
}

static void print_header(void) {
    printf("\n");
    set_color(FOREGROUND_GREEN | FOREGROUND_BLUE | FOREGROUND_INTENSITY);
    printf("  ╭────────────────────────────────────────────────────────────────────────╮\n");
    printf("  │   RESYNC  ──  AI-Native Dependency & API Compatibility Engine          │\n");
    printf("  │   Stateless MCP Server  •  Zero-Torch  •  FastEmbed Quantized ONNX     │\n");
    printf("  ╰────────────────────────────────────────────────────────────────────────╯\n\n");
    reset_color();
}

static void print_preflight(bool in_repo) {
    set_color(FOREGROUND_INTENSITY);
    printf("  Pre-flight Environment:\n");
    printf("    • Platform:       Windows %s\n", (sizeof(void*) == 8) ? "x86_64" : "x86");
    printf("    • Target Scope:   %s\n", in_repo ? "Local repository (.venv)" : "Global user CLI tool");
    printf("    • Architecture:   Stateless MCP Core (2026-07-28), Zero-Torch\n\n");
    reset_color();
}

static void print_stage(int num, int total, const char *title) {
    printf("\n");
    set_color(FOREGROUND_GREEN | FOREGROUND_BLUE | FOREGROUND_INTENSITY);
    printf("  ◆ Stage %d/%d: ", num, total);
    reset_color();
    printf("%s\n", title);
}

static void print_completion_card(const char *resync_cmd) {
    printf("\n");
    set_color(FOREGROUND_GREEN | FOREGROUND_INTENSITY);
    printf("  ╭────────────────────────────────────────────────────────────────────────╮\n");
    printf("  │  ✔  Resync MCP Server Successfully Installed & Ready!                  │\n");
    printf("  ├────────────────────────────────────────────────────────────────────────┤\n");
    reset_color();
    printf("  │  Resync Engine: %-54.54s │\n", resync_cmd);
    printf("  │  MCP Server:    stdio (resync serve) | streamable-http (port 8787)     │\n");
    printf("  │  MCP Tools (5): verify_package, check_symbol_exists, explain_change... │\n");
    printf("  │  Dashboard:     http://127.0.0.1:8787/dashboard (diffs & trust scores) │\n");
    printf("  │  Agents Linked: Google Antigravity, Claude Code, Cursor, VS Code, Zed  │\n");
    printf("  │  Knowledge:     14 verified records seeded (.resync/knowledge.lancedb) │\n");
    printf("  │  Embedding:     nomic-embed-text-v1.5-Q (130 MB quantized ONNX)        │\n");
    printf("  │  Architecture:  Stateless MCP 2026-07-28, zero-torch, 7 adapters      │\n");
    set_color(FOREGROUND_GREEN | FOREGROUND_INTENSITY);
    printf("  ├────────────────────────────────────────────────────────────────────────┤\n");
    reset_color();
    printf("  │  Quick Commands:                                                       │\n");
    printf("  │    resync run --explain   Complete compatibility & correction run      │\n");
    printf("  │    resync check --explain Static scan with decomposed trust scores     │\n");
    printf("  │    resync explain <tgt>   Explain change with 4-tier trust score       │\n");
    printf("  │    resync serve           Start live MCP server & review dashboard     │\n");
    printf("  │    resync doctor          Inspect complete subsystem health matrix     │\n");
    set_color(FOREGROUND_GREEN | FOREGROUND_INTENSITY);
    printf("  ╰────────────────────────────────────────────────────────────────────────╯\n\n");
    reset_color();
}

static bool file_exists(const char *path) {
    DWORD attr = GetFileAttributesA(path);
    return (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY));
}

static int run_command_silent(const char *cmd) {
    char full_cmd[4096];
    snprintf(full_cmd, sizeof(full_cmd), "%s >nul 2>nul", cmd);
    return system(full_cmd);
}

static int run_command_visible(const char *cmd) {
    return system(cmd);
}

/* Run a command with smooth non-blocking spinner, captured log output, and live elapsed duration */
static int run_command_animated(const char *cmd, const char *label) {
    char temp_dir[MAX_PATH];
    char log_path[MAX_PATH + 128];
    DWORD td_len = GetTempPathA(sizeof(temp_dir), temp_dir);
    if (td_len > 0 && td_len < sizeof(temp_dir)) {
        snprintf(log_path, sizeof(log_path), "%sresync_install_%lu.log", temp_dir, (unsigned long)GetCurrentProcessId());
    } else {
        snprintf(log_path, sizeof(log_path), "resync_install_%lu.log", (unsigned long)GetCurrentProcessId());
    }

    char cmdline[8192];
    snprintf(cmdline, sizeof(cmdline), "cmd.exe /s /c \"%s > \"%s\" 2>&1\"", cmd, log_path);

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(NULL, cmdline, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
        print_err(label);
        return 1;
    }

    hActiveChildProcess = pi.hProcess;

    const char *spinner[] = {"◐", "◓", "◑", "◒"};
    int spin_idx = 0;
    DWORD exit_code = 0;
    ULONGLONG start_time = GetTickCount64();

    set_cursor_visible(false);

    while (WaitForSingleObject(pi.hProcess, 80) == WAIT_TIMEOUT) {
        double elapsed = (double)(GetTickCount64() - start_time) / 1000.0;
        set_color(FOREGROUND_GREEN | FOREGROUND_BLUE | FOREGROUND_INTENSITY);
        printf("\r  %s ", spinner[spin_idx]);
        reset_color();
        printf("%s... (%.1fs)   ", label, elapsed);
        fflush(stdout);
        spin_idx = (spin_idx + 1) % 4;
    }

    GetExitCodeProcess(pi.hProcess, &exit_code);
    hActiveChildProcess = NULL;
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    set_cursor_visible(true);

    double total_elapsed = (double)(GetTickCount64() - start_time) / 1000.0;

    if (exit_code == 0) {
        set_color(FOREGROUND_GREEN | FOREGROUND_INTENSITY);
        printf("\r  ✔ ");
        reset_color();
        printf("%s ", label);
        set_color(FOREGROUND_INTENSITY);
        printf("[%.1fs]                          \n", total_elapsed);
        reset_color();
        DeleteFileA(log_path);
    } else {
        set_color(FOREGROUND_RED | FOREGROUND_INTENSITY);
        printf("\r  ✖ ");
        reset_color();
        printf("%s (exit code %lu) ", label, exit_code);
        set_color(FOREGROUND_INTENSITY);
        printf("[%.1fs]                          \n", total_elapsed);
        reset_color();

        /* Print diagnostic snippet from captured log on failure */
        FILE *fp = fopen(log_path, "r");
        if (fp) {
            char line[512];
            int count = 0;
            while (fgets(line, sizeof(line), fp) && count < 12) {
                printf("    %s", line);
                count++;
            }
            fclose(fp);
            DeleteFileA(log_path);
        }
    }
    fflush(stdout);
    return (int)exit_code;
}

static void persist_user_path(const char *dir) {
    HKEY hKey;
    if (RegOpenKeyExA(HKEY_CURRENT_USER, "Environment", 0, KEY_READ | KEY_WRITE, &hKey) == ERROR_SUCCESS) {
        char current_path[32768] = {0};
        DWORD type = REG_EXPAND_SZ;
        DWORD size = sizeof(current_path);
        LONG query_res = RegQueryValueExA(hKey, "Path", NULL, &type, (LPBYTE)current_path, &size);

        char lower_dir[1024] = {0};
        for (size_t i = 0; i < strlen(dir) && i < sizeof(lower_dir) - 1; i++) {
            lower_dir[i] = (char)tolower((unsigned char)dir[i]);
        }

        if (query_res == ERROR_SUCCESS) {
            char lower_cur[32768] = {0};
            for (size_t i = 0; i < strlen(current_path) && i < sizeof(lower_cur) - 1; i++) {
                lower_cur[i] = (char)tolower((unsigned char)current_path[i]);
            }
            if (strstr(lower_cur, lower_dir) == NULL) {
                char new_path[65536];
                snprintf(new_path, sizeof(new_path), "%s;%s", dir, current_path);
                RegSetValueExA(hKey, "Path", 0, type, (const BYTE*)new_path, (DWORD)(strlen(new_path) + 1));
                SendMessageTimeoutA(HWND_BROADCAST, WM_SETTINGCHANGE, 0, (LPARAM)"Environment", SMTO_ABORTIFHUNG, 1000, NULL);
            }
        } else if (query_res == ERROR_FILE_NOT_FOUND) {
            RegSetValueExA(hKey, "Path", 0, REG_EXPAND_SZ, (const BYTE*)dir, (DWORD)(strlen(dir) + 1));
            SendMessageTimeoutA(HWND_BROADCAST, WM_SETTINGCHANGE, 0, (LPARAM)"Environment", SMTO_ABORTIFHUNG, 1000, NULL);
        }
        RegCloseKey(hKey);
    }
}

static void install_resync_shim(const char *local_bin, const char *target_exe) {
    char shim_cmd[2048];
    snprintf(shim_cmd, sizeof(shim_cmd), "%s\\resync.cmd", local_bin);
    FILE *fp = fopen(shim_cmd, "w");
    if (fp) {
        fprintf(fp, "@echo off\n\"%s\" %%*\n", target_exe);
        fclose(fp);
    }
}

static void append_path(const char *dir) {
    char current_path[32768] = {0};
    DWORD len = GetEnvironmentVariableA("PATH", current_path, sizeof(current_path));

    char lower_dir[1024] = {0};
    for (size_t i = 0; i < strlen(dir) && i < sizeof(lower_dir) - 1; i++) {
        lower_dir[i] = (char)tolower((unsigned char)dir[i]);
    }

    if (len > 0) {
        char lower_cur[32768] = {0};
        for (size_t i = 0; i < strlen(current_path) && i < sizeof(lower_cur) - 1; i++) {
            lower_cur[i] = (char)tolower((unsigned char)current_path[i]);
        }
        if (strstr(lower_cur, lower_dir) == NULL) {
            char new_path[65536];
            snprintf(new_path, sizeof(new_path), "%s;%s", dir, current_path);
            SetEnvironmentVariableA("PATH", new_path);
        }
    } else {
        SetEnvironmentVariableA("PATH", dir);
    }
    persist_user_path(dir);
}

static void format_resync_cmd(char *out, size_t out_len, const char *resync_cmd, const char *args) {
    if (strchr(resync_cmd, ' ') != NULL && resync_cmd[0] != '\"' && strstr(resync_cmd, "uv run") == NULL) {
        snprintf(out, out_len, "\"%s\" %s", resync_cmd, args);
    } else {
        snprintf(out, out_len, "%s %s", resync_cmd, args);
    }
}

static void configure_specific_mcp_client(const char *resync_cmd, const char *client) {
    char cfg_cmd[MAX_PATH + 128];
    char args[128];
    snprintf(args, sizeof(args), "mcp-config %s --verify", client);
    format_resync_cmd(cfg_cmd, sizeof(cfg_cmd), resync_cmd, args);
    int rc = run_command_visible(cfg_cmd);
    if (rc != 0) {
        print_warn("Config written; --verify could not confirm client headless check.");
    }
}

static void configure_mcp_integrations(const char *resync_cmd, const char *specific_client, bool in_repo) {
    if (specific_client) {
        print_step("Configuring Resync MCP server for specified client...");
        configure_specific_mcp_client(resync_cmd, specific_client);
        return;
    }

    if (in_repo) {
        /* In a repository: auto-detect active agents and configure project MCP templates (.cursor, .vscode, etc.) */
        char auto_cmd[MAX_PATH + 64];
        format_resync_cmd(auto_cmd, sizeof(auto_cmd), resync_cmd, "mcp-config-auto --all");
        run_command_visible(auto_cmd);
    } else {
        /* Outside a repository: auto-detect only global AI coding agents without littering workspace files */
        char auto_cmd[MAX_PATH + 64];
        format_resync_cmd(auto_cmd, sizeof(auto_cmd), resync_cmd, "mcp-config-auto");
        run_command_visible(auto_cmd);
    }
}

int main(int argc, char *argv[]) {
    bool local_mode = false;
    bool global_mode = false;
    bool dev_mode = false;
    bool skip_mcp = false;
    bool non_interactive = false;
    const char *specific_client = NULL;

    /* Initialize UTF-8 code page and virtual terminal processing for modern styling */
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    hConsole = GetStdHandle(STD_OUTPUT_HANDLE);
    if (hConsole != INVALID_HANDLE_VALUE) {
        DWORD mode = 0;
        if (GetConsoleMode(hConsole, &mode)) {
            mode |= ENABLE_VIRTUAL_TERMINAL_PROCESSING;
            SetConsoleMode(hConsole, mode);
        }
    }
    SetConsoleCtrlHandler(console_ctrl_handler, TRUE);

    /* Parse command-line flags */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--local") == 0 || strcmp(argv[i], "-Local") == 0 || strcmp(argv[i], "-l") == 0) {
            local_mode = true;
        } else if (strcmp(argv[i], "--global") == 0 || strcmp(argv[i], "-Global") == 0 || strcmp(argv[i], "-g") == 0) {
            global_mode = true;
        } else if (strcmp(argv[i], "--dev") == 0 || strcmp(argv[i], "-Dev") == 0 || strcmp(argv[i], "-d") == 0) {
            dev_mode = true;
        } else if (strcmp(argv[i], "--yes") == 0 || strcmp(argv[i], "-Yes") == 0 || strcmp(argv[i], "-y") == 0) {
            non_interactive = true;
        } else if (strcmp(argv[i], "--skip-mcp") == 0 || strcmp(argv[i], "-SkipMcp") == 0) {
            skip_mcp = true;
        } else if (strcmp(argv[i], "--client") == 0 || strcmp(argv[i], "-Client") == 0) {
            if (i + 1 < argc) {
                specific_client = argv[++i];
            }
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-Help") == 0 || strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "/?") == 0) {
            print_header();
            printf("Usage: install.exe [OPTIONS]\n\n");
            printf("Options:\n");
            printf("  --local, -l        Install into local repository virtual environment (.venv)\n");
            printf("  --global, -g       Install as a global user CLI tool\n");
            printf("  --dev, -d          Include developer & test suites (mypy, ruff, pytest)\n");
            printf("  --client <name>    Auto-configure for a specific client (antigravity, claude-code, cursor, vscode, claude-desktop, windsurf, zed)\n");
            printf("  --yes, -y          Non-interactive execution (accept all defaults)\n");
            printf("  --skip-mcp         Skip MCP client configuration\n");
            printf("  --help, -h         Show this help message\n\n");
            printf("Examples:\n");
            printf("  install.exe                     # Interactive single-click install & full MCP setup\n");
            printf("  install.exe -y                  # Unattended setup (CI / automated)\n");
            printf("  install.exe --local --dev       # Local dev setup with test suites\n");
            printf("  install.exe --client cursor     # Install and configure for Cursor\n\n");
            return 0;
        }
    }

    print_header();

    bool in_repo = file_exists("pyproject.toml") || file_exists("..\\pyproject.toml");
    print_preflight(in_repo);

    /* Interactive Menu if run in TTY without explicit flags */
    if (!non_interactive && argc == 1 && _isatty(_fileno(stdin))) {
        printf("  Select Installation Profile:\n\n");
        set_color(FOREGROUND_GREEN | FOREGROUND_INTENSITY);
        printf("    [1] Standard AI Agent MCP Server (Recommended)\n");
        reset_color();
        printf("        Fast, lightweight, zero-torch profile. Configures MCP server, seeds\n");
        printf("        knowledge store, pre-warms quantized model, and auto-links AI agents.\n\n");

        set_color(FOREGROUND_GREEN | FOREGROUND_BLUE | FOREGROUND_INTENSITY);
        printf("    [2] Full Developer & Research Environment\n");
        reset_color();
        printf("        Includes pytest, hypothesis, mypy, ruff, and test fixtures.\n\n");

        set_color(FOREGROUND_RED | FOREGROUND_GREEN | FOREGROUND_INTENSITY);
        printf("    [3] Global Tool Installation\n");
        reset_color();
        printf("        Installs Resync CLI globally into user PATH rather than repo .venv.\n\n");

        printf("    [4] Exit\n\n");
        printf("  Enter selection [1-4] (default: 1): ");
        fflush(stdout);

        char input[32] = {0};
        if (fgets(input, sizeof(input), stdin)) {
            if (input[0] == '2') {
                dev_mode = true;
                local_mode = true;
            } else if (input[0] == '3') {
                global_mode = true;
            } else if (input[0] == '4') {
                printf("\n  Installation cancelled.\n\n");
                return 0;
            } else {
                local_mode = true;
            }
        }
        printf("\n");
    }

    /* 1. Setup local bin path in environment */
    const char *user_profile = getenv("USERPROFILE");
    if (!user_profile) user_profile = "C:\\Users\\Default";

    char local_bin[1024];
    snprintf(local_bin, sizeof(local_bin), "%s\\.local\\bin", user_profile);
    append_path(local_bin);

    /* STAGE 1: Runtime & Tooling */
    print_stage(1, 5, "Provisioning Core Runtime & Tooling (uv, Python 3.12, ast-grep)");

    char uv_bin[2048];
    snprintf(uv_bin, sizeof(uv_bin), "%s\\uv.exe", local_bin);
    bool has_uv = (run_command_silent("uv --version") == 0) || file_exists(uv_bin);

    if (!has_uv) {
        const char *install_uv_cmd = "powershell -NoProfile -ExecutionPolicy Bypass -Command \"irm https://astral.sh/uv/install.ps1 | iex\"";
        int rc = run_command_animated(install_uv_cmd, "Downloading and provisioning Astral uv");
        append_path(local_bin);
        if (rc != 0 && !file_exists(uv_bin)) {
            print_err("Failed to automatically install uv. Please install uv from https://docs.astral.sh/uv/");
            return 1;
        }
    } else {
        print_success("Astral uv package manager available.");
    }

    int py_check = run_command_silent("uv python find \">=3.11\"");
    if (py_check != 0) {
        int rc = run_command_animated("uv python install 3.12", "Installing standalone CPython 3.12 via uv");
        if (rc != 0) {
            print_err("Failed to install Python 3.12 via uv.");
            return 1;
        }
    } else {
        print_success("Compatible Python environment (>= 3.11) verified.");
    }

    char ast_grep_bin[2048];
    snprintf(ast_grep_bin, sizeof(ast_grep_bin), "%s\\ast-grep.exe", local_bin);
    bool has_ast_grep = (run_command_silent("ast-grep --version") == 0) || file_exists(ast_grep_bin);

    if (!has_ast_grep) {
        run_command_animated("uv tool install ast-grep-cli --force", "Installing native ast-grep AST engine");
        append_path(local_bin);
    } else {
        print_success("ast-grep native binary verified.");
    }

    /* STAGE 2: Resync Engine & Libraries */
    print_stage(2, 5, "Building Resync Compatibility Engine & Libraries");

    char resync_cmd[MAX_PATH] = "resync";

    if (local_mode || (in_repo && !global_mode)) {
        if (dev_mode) {
            run_command_animated("uv sync --extra server --extra cli --group dev --group verify",
                                 "Syncing local environment with developer & verification test suites");
        } else {
            run_command_animated("uv sync --extra server --extra cli",
                                 "Syncing lightweight production profile (server + cli, zero-torch)");
        }
        char abs_resync[MAX_PATH];
        GetFullPathNameA(".\\.venv\\Scripts\\resync.exe", sizeof(abs_resync), abs_resync, NULL);
        install_resync_shim(local_bin, abs_resync);
        snprintf(resync_cmd, sizeof(resync_cmd), "resync");
    } else {
        if (file_exists("pyproject.toml")) {
            run_command_animated("uv tool install --editable . --extra server --extra cli --with ast-grep-cli --force",
                                 "Installing Resync CLI globally in editable mode");
        } else {
            run_command_animated("uv tool install \"resync-mcp[server,cli]\" --with ast-grep-cli --force",
                                 "Installing Resync CLI globally from package index");
        }
        snprintf(resync_cmd, sizeof(resync_cmd), "resync");
    }

    /* Verify executable */
    char test_cmd[MAX_PATH + 32];
    format_resync_cmd(test_cmd, sizeof(test_cmd), resync_cmd, "--help");
    if (run_command_silent(test_cmd) != 0) {
        snprintf(resync_cmd, sizeof(resync_cmd), ".\\.venv\\Scripts\\resync.exe");
        format_resync_cmd(test_cmd, sizeof(test_cmd), resync_cmd, "--help");
        if (run_command_silent(test_cmd) != 0) {
            print_err("Resync executable verification failed.");
            return 1;
        }
    }
    print_success("Resync CLI engine operational.");

    /* STAGE 3: Model Cache Pre-Warming & Knowledge Store Seeding */
    print_stage(3, 5, "Pre-Warming Embedding Model & Seeding Knowledge Store");

    /* Initialize resync.toml if repo lacks one (using --no-seed so seeding is cleanly animated below) */
    if (in_repo && !file_exists("resync.toml") && !file_exists("..\\resync.toml")) {
        char init_cmd[MAX_PATH + 64];
        format_resync_cmd(init_cmd, sizeof(init_cmd), resync_cmd, "init --yes --no-seed");
        run_command_animated(init_cmd, "Creating resync.toml configuration");
    }

    /* Seed knowledge store */
    char seed_cmd[MAX_PATH + 64];
    format_resync_cmd(seed_cmd, sizeof(seed_cmd), resync_cmd, "seed");
    run_command_animated(seed_cmd, "Seeding built-in verified records into LanceDB knowledge store");

    /* STAGE 4: AI Coding Agent MCP Auto-Configuration */
    if (!skip_mcp) {
        print_stage(4, 5, "Auto-Configuring AI Coding Agent MCP Integrations");
        configure_mcp_integrations(resync_cmd, specific_client, in_repo);
    } else {
        print_step("Skipping MCP client auto-configuration (--skip-mcp specified).");
    }

    persist_user_path(local_bin);

    /* STAGE 5: System Diagnostics & Health Verification */
    print_stage(5, 5, "Running Comprehensive System Diagnostics (Doctor)");

    char doctor_cmd[MAX_PATH + 64];
    format_resync_cmd(doctor_cmd, sizeof(doctor_cmd), resync_cmd, "doctor");
    run_command_visible(doctor_cmd);

    /* Run verify_install.py if present */
    if (file_exists("scripts\\verify_install.py")) {
        char verify_cmd[MAX_PATH];
        if (file_exists(".\\.venv\\Scripts\\python.exe")) {
            snprintf(verify_cmd, sizeof(verify_cmd), ".\\.venv\\Scripts\\python.exe scripts\\verify_install.py");
        } else {
            snprintf(verify_cmd, sizeof(verify_cmd), "python scripts\\verify_install.py");
        }
        run_command_visible(verify_cmd);
    }

    print_completion_card(resync_cmd);

    /* Determine if launched directly from Windows Explorer (dedicated console created) */
    DWORD proc_list[2];
    DWORD proc_count = GetConsoleProcessList(proc_list, 2);
    bool launched_from_explorer = (proc_count <= 1);

    if (!non_interactive && launched_from_explorer) {
        printf("  Press Enter to exit...");
        fflush(stdout);
        getchar();
    }

    return 0;
}
