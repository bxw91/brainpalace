#!/usr/bin/env bash
# BrainPalace guided setup.
#
# Fully interactive. Every decision is a prompt. No flags.
# Run directly from the network:
#
#   curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/setup.sh | bash
#
# Or from a local checkout:
#
#   bash scripts/setup.sh
#
# Covers:
#   1. Install the `brainpalace` binary (CLI + server via pipx)
#   2. Initialise the project and start the HTTP server
#   3. Configure an embedding / summarisation provider
#   4. Index the project
#   5. Wire an MCP client config (optional)
#   6. Verify with `brainpalace status` and an optional sample query
#
# Requires an interactive terminal (reads from /dev/tty). Exits with a
# clear error if stdin / tty is not attached.
set -euo pipefail

REPO_URL="https://github.com/bxw91/brainpalace.git"
REF="main"

# -----------------------------------------------------------------------------
# Pre-flight: must have a TTY
# -----------------------------------------------------------------------------

if [[ ! -e /dev/tty ]] || ! { : >/dev/tty; } 2>/dev/null; then
    echo "ERROR: this script is interactive and needs a terminal." >&2
    echo "If you piped through curl in a non-interactive shell, run:" >&2
    echo "    curl -sSL <url>/setup.sh -o /tmp/ab-setup.sh && bash /tmp/ab-setup.sh" >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# Helpers (all I/O via /dev/tty so curl | bash works)
# -----------------------------------------------------------------------------

c_bold=$(printf '\033[1m');     c_reset=$(printf '\033[0m')
c_cyan=$(printf '\033[1;36m');  c_yel=$(printf '\033[1;33m')
c_red=$(printf '\033[1;31m');   c_gr=$(printf '\033[1;32m')

say()  { printf '%s==>%s %s\n' "$c_bold" "$c_reset" "$*" >/dev/tty; }
step() { printf '\n%s--- %s ---%s\n' "$c_cyan" "$*" "$c_reset" >/dev/tty; }
warn() { printf '%sWARN:%s %s\n' "$c_yel" "$c_reset" "$*" >/dev/tty; }
ok()   { printf '%s%s%s\n' "$c_gr" "$*" "$c_reset" >/dev/tty; }
errx() { printf '%sERROR:%s %s\n' "$c_red" "$c_reset" "$*" >/dev/tty; exit 2; }

ask() {
    # ask "Prompt" "default" -> echoes user answer (or default if blank)
    local prompt="$1" default="${2:-}" reply
    if [[ -n "$default" ]]; then
        printf '%s [%s]: ' "$prompt" "$default" >/dev/tty
    else
        printf '%s: ' "$prompt" >/dev/tty
    fi
    IFS= read -r reply </dev/tty || reply=""
    printf '%s' "${reply:-$default}"
}

ask_required() {
    # Like ask but re-prompts on empty
    local prompt="$1" reply=""
    while [[ -z "$reply" ]]; do
        printf '%s: ' "$prompt" >/dev/tty
        IFS= read -r reply </dev/tty || reply=""
        [[ -z "$reply" ]] && warn "Required."
    done
    printf '%s' "$reply"
}

confirm() {
    # confirm "Prompt" "y|n" -> exit 0 if yes
    local prompt="$1" default="${2:-n}" reply hint
    [[ "$default" == "y" ]] && hint="[Y/n]" || hint="[y/N]"
    printf '%s %s ' "$prompt" "$hint" >/dev/tty
    IFS= read -r reply </dev/tty || reply=""
    reply="${reply:-$default}"
    [[ "${reply,,}" == "y" || "${reply,,}" == "yes" ]]
}

pick() {
    # pick "Prompt" "default-num" "label1" "label2" ...
    # prints chosen label number to stdout
    local prompt="$1" default="$2"; shift 2
    local i=1
    for opt in "$@"; do
        printf '   %d) %s\n' "$i" "$opt" >/dev/tty
        i=$((i+1))
    done
    local choice
    choice="$(ask "$prompt" "$default")"
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > $# )); then
        warn "Invalid choice — using default ($default)."
        choice="$default"
    fi
    printf '%s' "$choice"
}

# -----------------------------------------------------------------------------
# Banner
# -----------------------------------------------------------------------------

clear >/dev/tty 2>/dev/null || true
cat >/dev/tty <<EOF
${c_bold}BrainPalace — guided setup${c_reset}
Source: $REPO_URL @ $REF

This script will ask before every action. Six steps:
  1. Install the brainpalace binary (pipx)
  2. Initialise project + start server
  3. Configure provider
  4. Index project
  5. Wire MCP client (optional)
  6. Verify

EOF
confirm "Continue?" "y" || { say "Aborted."; exit 0; }

# -----------------------------------------------------------------------------
# Step 1 — install
# -----------------------------------------------------------------------------

step "Step 1/6 — Install brainpalace binary"

if command -v brainpalace >/dev/null 2>&1; then
    CURRENT_VERSION="$(brainpalace --version 2>/dev/null || echo unknown)"
    say "Already installed: $CURRENT_VERSION  ($(command -v brainpalace))"
    if confirm "Reinstall / upgrade now?" "n"; then
        DO_INSTALL=1
    else
        DO_INSTALL=0
    fi
else
    say "brainpalace not found on PATH."
    if confirm "Install now via install.sh (pipx)?" "y"; then
        DO_INSTALL=1
    else
        errx "Cannot continue without the brainpalace binary."
    fi
fi

if [[ "$DO_INSTALL" -eq 1 ]]; then
    USE_LOCAL=""
    if confirm "Install from a local checkout instead of GitHub?" "n"; then
        USE_LOCAL="$(ask_required "Path to local checkout")"
        [[ -x "$USE_LOCAL/scripts/install.sh" ]] \
            || errx "install.sh not found at $USE_LOCAL/scripts/install.sh"
    fi

    say "Running install.sh ..."
    if [[ -n "$USE_LOCAL" ]]; then
        bash "$USE_LOCAL/scripts/install.sh" --local "$USE_LOCAL" </dev/tty >/dev/tty
    else
        INSTALL_URL="${REPO_URL%.git}"
        INSTALL_URL="${INSTALL_URL/github.com/raw.githubusercontent.com}/${REF}/scripts/install.sh"
        curl -sSL "$INSTALL_URL" | bash >/dev/tty
    fi

    command -v brainpalace >/dev/null 2>&1 \
        || errx "'brainpalace' still not on PATH. Check pipx + 'pipx ensurepath'."
    ok "Installed: $(brainpalace --version)"
fi

AB_BIN="$(command -v brainpalace)"

# -----------------------------------------------------------------------------
# Step 2 — pick project + configure provider (BEFORE init/start so the
# server inherits the API key from this script's environment when it
# boots in step 3; otherwise the long-lived server process would never
# see the key the user just pasted).
# -----------------------------------------------------------------------------

step "Step 2/6 — Project + provider"

PROJECT="$(ask "Project root" "$PWD")"
PROJECT="${PROJECT/#\~/$HOME}"
[[ -d "$PROJECT" ]] || errx "Path does not exist: $PROJECT"
PROJECT="$(cd "$PROJECT" && pwd)"
say "Project: $PROJECT"

if [[ -f "$PROJECT/.brainpalace/runtime.json" ]]; then
    say "This project already has .brainpalace/ — init will be a no-op."
fi

say "Configure the provider FIRST so the server we start in step 3 sees the API key."

# env-var names match the server defaults and the Claude Code plugin
# wizard. The server resolves the actual var name from `api_key_env` in
# config.yaml — see post-wizard patch below.
declare -A PROVIDER_ENV=(
    [openai]=OPENAI_API_KEY
    [anthropic]=ANTHROPIC_API_KEY
    [cohere]=COHERE_API_KEY
    [gemini]=GOOGLE_API_KEY
    [grok]=XAI_API_KEY
)

DETECTED=""
for var in OPENAI_API_KEY ANTHROPIC_API_KEY COHERE_API_KEY GOOGLE_API_KEY XAI_API_KEY; do
    [[ -n "${!var:-}" ]] && DETECTED="$DETECTED $var"
done
if [[ -n "$DETECTED" ]]; then
    say "Detected env vars:$DETECTED"
else
    say "No provider keys detected in your environment."
fi

echo >/dev/tty
echo "Which provider do you want to set up?" >/dev/tty
P_CHOICE="$(pick "Choice 1-8" "8" \
    "openai     (cloud — needs OPENAI_API_KEY)" \
    "anthropic  (cloud — needs ANTHROPIC_API_KEY)" \
    "cohere     (cloud — needs COHERE_API_KEY)" \
    "gemini     (cloud — needs GOOGLE_API_KEY)" \
    "grok       (cloud — needs XAI_API_KEY)" \
    "ollama     (local — needs Ollama running)" \
    "skip       (set up later with 'brainpalace config wizard')" \
    "wizard now (run the full picker without my hints)")"

case "$P_CHOICE" in
    1) PROVIDER="openai" ;;
    2) PROVIDER="anthropic" ;;
    3) PROVIDER="cohere" ;;
    4) PROVIDER="gemini" ;;
    5) PROVIDER="grok" ;;
    6) PROVIDER="ollama" ;;
    7) PROVIDER="skip" ;;
    8) PROVIDER="wizard" ;;
esac

case "$PROVIDER" in
    skip)
        warn "Skipping provider — search will fail until you run 'brainpalace config wizard'."
        ;;
    wizard)
        say "Launching brainpalace config wizard ..."
        (cd "$PROJECT" && "$AB_BIN" config wizard) </dev/tty >/dev/tty
        ;;
    ollama)
        OLLAMA_URL="$(ask "Ollama base URL" "${OLLAMA_BASE_URL:-http://127.0.0.1:11434}")"
        if curl -fsS --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
            ok "Reached Ollama at $OLLAMA_URL"
        else
            warn "Could not reach $OLLAMA_URL — wizard will still let you continue."
        fi
        say "Launching wizard with OLLAMA_BASE_URL=$OLLAMA_URL"
        (cd "$PROJECT" && OLLAMA_BASE_URL="$OLLAMA_URL" "$AB_BIN" config wizard) </dev/tty >/dev/tty
        ;;
    *)
        VAR="${PROVIDER_ENV[$PROVIDER]:-}"
        if [[ -z "$VAR" ]]; then
            errx "internal: no env-var mapping for provider $PROVIDER"
        fi
        if [[ -z "${!VAR:-}" ]]; then
            warn "$VAR not in environment."
            if confirm "Set it now for this script's run?" "y"; then
                printf 'Paste your %s value (input hidden): ' "$VAR" >/dev/tty
                IFS= read -rs KEY </dev/tty || KEY=""
                echo >/dev/tty
                if [[ -n "$KEY" ]]; then
                    export "$VAR"="$KEY"
                    ok "$VAR exported for this session."
                    warn "Add 'export $VAR=...' to your shell rc for future runs."
                else
                    warn "Empty input — continuing without $VAR set."
                fi
            fi
        fi
        say "Launching brainpalace config wizard ..."
        (cd "$PROJECT" && "$AB_BIN" config wizard) </dev/tty >/dev/tty
        ;;
esac

# -----------------------------------------------------------------------------
# Post-wizard: patch api_key_env per provider.
#
# `brainpalace config wizard` writes provider + model but never prompts
# for `api_key_env`, so it defaults to OPENAI_API_KEY (embedding) /
# ANTHROPIC_API_KEY (summarization). For cohere / gemini / grok the
# server then reads the wrong env var. Patch config.yaml here so the
# server reads the var name the user actually exported above.
# -----------------------------------------------------------------------------

CFG="$PROJECT/.brainpalace/config.yaml"
if [[ -f "$CFG" && "$PROVIDER" != "skip" ]]; then
    # Use the brainpalace pipx venv's python (PyYAML guaranteed there).
    # Fall back to system python3 only if pipx env lookup fails.
    AB_PY="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null)/brainpalace-cli/bin/python"
    [[ -x "$AB_PY" ]] || AB_PY="python3"
    "$AB_PY" - "$CFG" <<'PY' >/dev/tty 2>&1 || warn "config.yaml api_key_env patch failed — set manually if you picked cohere/gemini/grok"
import sys, pathlib
try:
    import yaml
except ImportError:
    print("PyYAML missing on this python — skipping patch."); sys.exit(0)
p = pathlib.Path(sys.argv[1])
cfg = yaml.safe_load(p.read_text()) or {}
defaults = {
    "openai":    "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "cohere":    "COHERE_API_KEY",
    "gemini":    "GOOGLE_API_KEY",
    "grok":      "XAI_API_KEY",
}
changed = []
for section in ("embedding", "summarization"):
    s = cfg.get(section)
    if not isinstance(s, dict): continue
    prov = s.get("provider")
    if prov == "ollama": continue
    want = defaults.get(prov)
    if want and s.get("api_key_env") != want:
        s["api_key_env"] = want
        changed.append(f"{section}.api_key_env -> {want}")
if changed:
    p.write_text(yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False))
    print("Patched config.yaml: " + ", ".join(changed))
else:
    print("config.yaml api_key_env already correct.")
PY
fi

# -----------------------------------------------------------------------------
# Step 3 — init + start (server inherits provider env from this script)
# -----------------------------------------------------------------------------

step "Step 3/6 — Initialise project + start server"

WATCH="off"
if confirm "Enable file watcher (auto reindex on save)?" "y"; then
    WATCH="auto"
fi

WATCH_FLAG=""
[[ "$WATCH" == "auto" ]] && WATCH_FLAG="--watch auto"

say "Running: brainpalace init --start $WATCH_FLAG"
(cd "$PROJECT" && "$AB_BIN" init --start $WATCH_FLAG) >/dev/tty
ok "Server initialised and started."

if [[ "$PROVIDER" != "skip" && "$PROVIDER" != "ollama" && "$PROVIDER" != "wizard" ]]; then
    VAR_CHECK="${PROVIDER_ENV[$PROVIDER]:-}"
    if [[ -n "$VAR_CHECK" && -z "${!VAR_CHECK:-}" ]]; then
        warn "$VAR_CHECK not set — server will fail provider calls."
        warn "Stop and rerun with the key exported, or set it now and 'brainpalace stop && brainpalace start'."
    fi
fi

# -----------------------------------------------------------------------------
# Step 4 — index
# -----------------------------------------------------------------------------

step "Step 4/6 — Index project"

if confirm "Index the project now?" "y"; then
    INDEX_PATH="$(ask "Path to index (relative to project root, or absolute)" ".")"
    if confirm "Include code (AST chunking)? (no = docs only)" "y"; then
        CODE_FLAG=""
    else
        CODE_FLAG="--no-code"
    fi
    say "Running: brainpalace index $INDEX_PATH $CODE_FLAG"
    (cd "$PROJECT" && "$AB_BIN" index "$INDEX_PATH" $CODE_FLAG) >/dev/tty
    INDEXED_TARGET="$INDEX_PATH"
else
    INDEXED_TARGET="skipped"
    warn "No index — queries will return nothing until you run 'brainpalace index <path>'."
fi

# -----------------------------------------------------------------------------
# Step 5 — MCP client wiring
# -----------------------------------------------------------------------------

step "Step 5/6 — Wire an MCP client (optional)"

say "If you only use the CLI (or the Claude Code plugin), pick 'none'."
say "Otherwise pick the MCP client you use — its config file will be written"
say "with an absolute path so GUI-launched editors do not hit the PATH gotcha."

M_CHOICE="$(pick "Choice 1-7" "7" \
    "VS Code (GitHub Copilot agent mode) — .vscode/mcp.json" \
    "Cursor                              — .cursor/mcp.json" \
    "Cline                               — .cline/mcp.json" \
    "Continue                            — .continue/mcp.yaml" \
    "Kilo Code                           — .kilo/kilo.jsonc" \
    "Zed                                 — .zed/settings.json" \
    "none (CLI-only install)")"

case "$M_CHOICE" in
    1) MCP_CLIENT="vscode" ;;
    2) MCP_CLIENT="cursor" ;;
    3) MCP_CLIENT="cline" ;;
    4) MCP_CLIENT="continue" ;;
    5) MCP_CLIENT="kilo" ;;
    6) MCP_CLIENT="zed" ;;
    7) MCP_CLIENT="none" ;;
esac

write_file() {
    local path="$1" content="$2"
    if [[ -e "$path" ]]; then
        local backup="${path}.bak.$(date +%s)"
        warn "$path exists — backing up to $backup"
        cp "$path" "$backup"
    fi
    mkdir -p "$(dirname "$path")"
    printf '%s\n' "$content" > "$path"
    ok "Wrote $path"
}

if [[ "$MCP_CLIENT" != "none" ]]; then
    SCOPE_CHOICE="$(pick "Write config where?" "1" \
        "Project scope (in $PROJECT)" \
        "User scope  (HOME directory)")"
    if [[ "$SCOPE_CHOICE" == "2" ]]; then
        BASE="$HOME"
    else
        BASE="$PROJECT"
    fi

    case "$MCP_CLIENT" in
        vscode)
            write_file "$BASE/.vscode/mcp.json" "$(cat <<EOF
{
  "servers": {
    "brainpalace": {
      "type": "stdio",
      "command": "$AB_BIN",
      "args": ["mcp", "--ensure-server"]
    }
  }
}
EOF
)" ;;
        cursor)
            write_file "$BASE/.cursor/mcp.json" "$(cat <<EOF
{
  "mcpServers": {
    "brainpalace": {
      "command": "$AB_BIN",
      "args": ["mcp", "--ensure-server"]
    }
  }
}
EOF
)" ;;
        cline)
            write_file "$BASE/.cline/mcp.json" "$(cat <<EOF
{
  "mcpServers": {
    "brainpalace": {
      "command": "$AB_BIN",
      "args": ["mcp", "--ensure-server"],
      "disabled": false
    }
  }
}
EOF
)"
            warn "Cline's real config path varies — see docs/MCP_SETUP.md if Cline doesn't pick it up." ;;
        continue)
            write_file "$BASE/.continue/mcp.yaml" "$(cat <<EOF
mcpServers:
  - name: brainpalace
    command: $AB_BIN
    args: ["mcp", "--ensure-server"]
EOF
)" ;;
        kilo)
            write_file "$BASE/.kilo/kilo.jsonc" "$(cat <<EOF
{
  "mcp": {
    "brainpalace": {
      "type": "local",
      "command": ["$AB_BIN", "mcp", "--ensure-server"],
      "enabled": true,
      "timeout": 30000
    }
  }
}
EOF
)" ;;
        zed)
            write_file "$BASE/.zed/settings.json" "$(cat <<EOF
{
  "context_servers": {
    "brainpalace": {
      "command": {
        "path": "$AB_BIN",
        "args": ["mcp", "--ensure-server"]
      }
    }
  }
}
EOF
)" ;;
    esac
    ok "Absolute path $AB_BIN baked into the config (avoids PATH-inheritance failures)."
fi

# -----------------------------------------------------------------------------
# Step 6 — verify
# -----------------------------------------------------------------------------

step "Step 6/6 — Verify"

(cd "$PROJECT" && "$AB_BIN" status) >/dev/tty || warn "status returned non-zero"

if confirm "Run a sample query now?" "y"; then
    Q="$(ask "Query" "how does authentication work")"
    (cd "$PROJECT" && "$AB_BIN" query "$Q" --mode hybrid) >/dev/tty \
        || warn "Query failed — check provider config and index status."
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

cat >/dev/tty <<EOF

${c_gr}Setup complete.${c_reset}
  Binary:    $AB_BIN  ($("$AB_BIN" --version 2>/dev/null || echo "?"))
  Project:   $PROJECT
  Watcher:   $WATCH
  Provider:  $PROVIDER
  Indexed:   $INDEXED_TARGET
  MCP wire:  $MCP_CLIENT

${c_bold}Useful next commands${c_reset} (all auto-discover the project from CWD):
  brainpalace status
  brainpalace query "..." --mode hybrid
  brainpalace config wizard
  brainpalace list                # all running servers across projects

${c_bold}Add another project${c_reset} (binary is already installed — never reinstall):

  cd /path/to/other-project
  brainpalace init --start --watch auto
  brainpalace index .

Each project gets its own server on a separate auto-allocated port. The
provider config you set up here can be reused by copying
.brainpalace/config.yaml into the new project's .brainpalace/, or by
running 'brainpalace config wizard' fresh inside it. The exported API
key in your shell rc covers all projects.

To re-run this guided setup for a different project (provider + index
+ MCP-client wiring in one go), just run the same curl one-liner again
— step 1 will detect the binary and skip reinstall.

Docs:
  README.md                Install + quick start
  docs/INSTALL.md          Add-another-project + manual install + CI
  docs/USER_GUIDE.md       Full CLI reference
  docs/MCP_SETUP.md        Per-client MCP config
EOF
