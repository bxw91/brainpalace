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
# Covers (global-first):
#   1. Install the `brainpalace` binary (CLI + server via pipx)
#   2. Configure an embedding / summarisation provider GLOBALLY
#   3. Wire an MCP client config at user scope (optional)
#   4. Set up + index a project (optional — last step)
#   5. Verify with `brainpalace status` and an optional sample query
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
    printf '\n' >/dev/tty   # blank line before each question (visual separation)
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
    printf '\n' >/dev/tty   # blank line before each question (visual separation)
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
    printf '\n' >/dev/tty   # blank line before each question (visual separation)
    printf '%s %s ' "$prompt" "$hint" >/dev/tty
    IFS= read -r reply </dev/tty || reply=""
    reply="${reply:-$default}"
    [[ "${reply,,}" == "y" || "${reply,,}" == "yes" ]]
}

detect_local_checkout() {
    # Print the path to a brainpalace source checkout (this script run from a
    # clone), else return 1. Used to offer the "install from local checkout"
    # path ONLY when it's actually usable — a `curl | bash` user has no checkout
    # and should not be asked about one.
    local src here root
    src="${BASH_SOURCE[0]:-$0}"
    here="$(cd "$(dirname "$src")" 2>/dev/null && pwd)" || return 1
    root="$(dirname "$here")"   # .../scripts -> repo root
    if [[ -x "$root/scripts/install.sh" && -d "$root/brainpalace-cli" ]]; then
        printf '%s\n' "$root"; return 0
    fi
    if [[ -x "$PWD/scripts/install.sh" && -d "$PWD/brainpalace-cli" ]]; then
        printf '%s\n' "$PWD"; return 0
    fi
    return 1
}

latest_pypi_version() {
    # Print the latest published version of a PyPI package, or return 1 if it
    # can't be determined (offline, PyPI down). Best-effort — never fatal.
    local pkg="$1" out
    out="$(curl -fsSL "https://pypi.org/pypi/${pkg}/json" 2>/dev/null)" || return 1
    if command -v python3 >/dev/null 2>&1; then
        printf '%s' "$out" \
            | python3 -c 'import sys,json; print(json.load(sys.stdin)["info"]["version"])' \
              2>/dev/null
    else
        # Fallback: the info block is first, so its "version" is the first match.
        printf '%s' "$out" \
            | grep -oE '"version":[[:space:]]*"[^"]+"' | head -1 \
            | grep -oE '[0-9][^"]*'
    fi
}

xdg_config_yaml() {
    # Path to the global provider config the wizard --global writes and every
    # `brainpalace init` inherits. Honors XDG_CONFIG_HOME.
    printf '%s/brainpalace/config.yaml' "${XDG_CONFIG_HOME:-$HOME/.config}"
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

# Look up the version that will be installed (latest on PyPI) so the user sees
# it before committing to anything. Best-effort — never fatal.
LATEST_CLI="$(latest_pypi_version brainpalace-cli 2>/dev/null || true)"
if [[ -n "$LATEST_CLI" ]]; then
    VERSION_LINE="Version to install: ${LATEST_CLI} (latest on PyPI)"
else
    VERSION_LINE="Version to install: latest on PyPI (couldn't reach PyPI to check)"
fi

clear >/dev/tty 2>/dev/null || true
cat >/dev/tty <<EOF
${c_bold}BrainPalace — guided setup${c_reset}
Source: $REPO_URL @ $REF
$VERSION_LINE

This script will ask before every action. Five steps (global-first):
  1. Install the brainpalace binary (pipx)
  2. Configure provider globally
  3. Wire MCP client at user scope (optional)
  4. Set up + index a project (optional)
  5. Verify

EOF
confirm "Continue?" "y" || { say "Aborted."; exit 0; }

# -----------------------------------------------------------------------------
# Step 1 — install
# -----------------------------------------------------------------------------

step "Step 1/5 — Install brainpalace binary"

if command -v brainpalace >/dev/null 2>&1; then
    CURRENT_VERSION="$(brainpalace --version 2>/dev/null || echo unknown)"
    cur="$(printf '%s' "$CURRENT_VERSION" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    say "Already installed: $CURRENT_VERSION  ($(command -v brainpalace))"

    latest="$LATEST_CLI"   # already fetched for the banner
    prompt="Reinstall / upgrade now?"; default="n"
    if [[ -n "$latest" ]]; then
        if [[ -n "$cur" && "$cur" == "$latest" ]]; then
            say "Latest on PyPI: $latest — you're up to date."
            prompt="Reinstall anyway?"; default="n"
        else
            say "Latest on PyPI: $latest — update available."
            prompt="Update to $latest now?"; default="y"
        fi
    else
        say "(couldn't reach PyPI to check the latest version)"
    fi

    if confirm "$prompt" "$default"; then
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
    # Only offer the local-checkout path when one is actually present — most
    # users install from GitHub/PyPI and have no checkout to point at.
    local_root="$(detect_local_checkout || true)"
    if [[ -n "$local_root" ]] \
        && confirm "Local checkout detected at $local_root — install from it instead of GitHub?" "n"; then
        USE_LOCAL="$local_root"
    fi

    say "Running install.sh ..."
    say "This installs the CLI + server (full RAG/ML stack) into an isolated pipx"
    say "venv. The first install downloads several large packages — expect it to"
    say "take a few minutes."
    # Tell install.sh it runs inside guided setup so it suppresses its own
    # "Next steps" block — this script gives the (simpler) guidance at the end.
    export BRAINPALACE_GUIDED_SETUP=1
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
# Step 2 — configure provider GLOBALLY (no project yet). Written to the XDG
# global config that every later `brainpalace init` inherits, so the project
# step can be deferred to the end and made optional.
# -----------------------------------------------------------------------------

step "Step 2/5 — Provider / API key (global)"

say "Configure the embedding/summarization provider ONCE, globally."
say "Every project you set up later inherits ~/.config/brainpalace/config.yaml."

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

# Append a green "✓ <VAR> detected" tag to a provider label when that key is
# already exported, so the user sees at a glance which provider is ready to go.
det_tag() { [[ -n "${!1:-}" ]] && printf '   %s✓ %s detected%s' "$c_gr" "$1" "$c_reset"; }

echo >/dev/tty
echo "Which provider do you want to set up?" >/dev/tty
P_CHOICE="$(pick "Choice 1-8" "8" \
    "openai     (cloud — needs OPENAI_API_KEY)$(det_tag OPENAI_API_KEY)" \
    "anthropic  (cloud — needs ANTHROPIC_API_KEY)$(det_tag ANTHROPIC_API_KEY)" \
    "cohere     (cloud — needs COHERE_API_KEY)$(det_tag COHERE_API_KEY)" \
    "gemini     (cloud — needs GOOGLE_API_KEY)$(det_tag GOOGLE_API_KEY)" \
    "grok       (cloud — needs XAI_API_KEY)$(det_tag XAI_API_KEY)" \
    "ollama     (local — needs Ollama running)" \
    "skip       (set up later with 'brainpalace config wizard --global')" \
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

# Run the wizard GLOBALLY (from $HOME so no stray project .brainpalace/ is found).
case "$PROVIDER" in
    skip)
        warn "Skipping provider — search fails until you run 'brainpalace config wizard --global'."
        ;;
    wizard)
        say "Launching brainpalace config wizard (global) ..."
        (cd "$HOME" && "$AB_BIN" config wizard --global) </dev/tty >/dev/tty
        ;;
    ollama)
        OLLAMA_URL="$(ask "Ollama base URL" "${OLLAMA_BASE_URL:-http://127.0.0.1:11434}")"
        if curl -fsS --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
            ok "Reached Ollama at $OLLAMA_URL"
        else
            warn "Could not reach $OLLAMA_URL — wizard will still let you continue."
        fi
        say "Launching wizard (global) with OLLAMA_BASE_URL=$OLLAMA_URL"
        (cd "$HOME" && OLLAMA_BASE_URL="$OLLAMA_URL" "$AB_BIN" config wizard --global) </dev/tty >/dev/tty
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
        say "Launching brainpalace config wizard (global) ..."
        (cd "$HOME" && "$AB_BIN" config wizard --global) </dev/tty >/dev/tty
        ;;
esac

# -----------------------------------------------------------------------------
# Post-wizard: patch api_key_env per provider on the GLOBAL config.
#
# `brainpalace config wizard` writes provider + model but never prompts
# for `api_key_env`, so it defaults to OPENAI_API_KEY (embedding) /
# ANTHROPIC_API_KEY (summarization). For cohere / gemini / grok the
# server then reads the wrong env var. Patch config.yaml here so the
# server reads the var name the user actually exported above.
# -----------------------------------------------------------------------------

CFG="$(xdg_config_yaml)"
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
    print("Patched global config.yaml: " + ", ".join(changed))
else:
    print("Global config.yaml api_key_env already correct.")
PY
fi

# -----------------------------------------------------------------------------
# Step 3 — MCP client wiring (optional), user scope by default so it's
# machine-wide. Runs BEFORE the project step; project scope falls back to
# $HOME when no project has been chosen yet.
# -----------------------------------------------------------------------------

step "Step 3/5 — Wire an MCP client (optional, global)"

say "If you only use the CLI (or the Claude Code plugin), pick 'none'."
say "Otherwise pick the MCP client you use — its config file is written with an"
say "absolute path so GUI-launched editors do not hit the PATH gotcha."

ALL_MCP_KEYS=(vscode cursor cline continue kilo zed)
declare -A MCP_LABEL=(
    [vscode]="VS Code (GitHub Copilot agent mode) — .vscode/mcp.json"
    [cursor]="Cursor                              — .cursor/mcp.json"
    [cline]="Cline                               — .cline/mcp.json"
    [continue]="Continue                            — .continue/mcp.yaml"
    [kilo]="Kilo Code                           — .kilo/kilo.jsonc"
    [zed]="Zed                                 — .zed/settings.json"
)

# Best-effort detection: a client counts as present if its CLI is on PATH or its
# config/support dir exists. Used to show only relevant clients by default.
mcp_detected() {
    case "$1" in
        vscode)   command -v code   >/dev/null 2>&1 || [[ -d "$HOME/.vscode"   || -d "$HOME/.config/Code"   ]] ;;
        cursor)   command -v cursor >/dev/null 2>&1 || [[ -d "$HOME/.cursor"   || -d "$HOME/.config/Cursor" ]] ;;
        cline)    [[ -d "$HOME/.cline" ]] ;;
        continue) [[ -d "$HOME/.continue" ]] ;;
        kilo)     [[ -d "$HOME/.kilo" ]] ;;
        zed)      command -v zed    >/dev/null 2>&1 || [[ -d "$HOME/.zed"      || -d "$HOME/.config/zed"    ]] ;;
        *) return 1 ;;
    esac
}

# select_mcp <show_all_hatch:0|1> <key>... -> echoes chosen key | "none" | "__all__"
select_mcp() {
    local hatch="$1"; shift
    local keys=("$@") labels=() k
    for k in "${keys[@]}"; do labels+=("${MCP_LABEL[$k]}"); done
    local none_idx=$(( ${#keys[@]} + 1 ))
    labels+=("none (CLI-only install)")
    [[ "$hatch" == "1" ]] && labels+=("other — show all supported clients")
    local idx; idx="$(pick "Choice (number)" "$none_idx" "${labels[@]}")"
    local sel="${labels[$((idx-1))]}"
    case "$sel" in
        none*)  echo "none" ;;
        other*) echo "__all__" ;;
        *)      echo "${keys[$((idx-1))]}" ;;
    esac
}

DETECTED_MCP=()
for k in "${ALL_MCP_KEYS[@]}"; do mcp_detected "$k" && DETECTED_MCP+=("$k"); done

if [[ ${#DETECTED_MCP[@]} -gt 0 ]]; then
    say "Auto-detected MCP-capable clients on this machine (pick 'other' to see all):"
    MCP_CLIENT="$(select_mcp 1 "${DETECTED_MCP[@]}")"
    [[ "$MCP_CLIENT" == "__all__" ]] && MCP_CLIENT="$(select_mcp 0 "${ALL_MCP_KEYS[@]}")"
else
    say "No MCP clients auto-detected — showing all supported clients:"
    MCP_CLIENT="$(select_mcp 0 "${ALL_MCP_KEYS[@]}")"
fi

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
    SCOPE_CHOICE="$(pick "Write config where?" "2" \
        "Project scope (in the project you set up below)" \
        "User scope  (HOME directory — recommended, applies everywhere)")"
    if [[ "$SCOPE_CHOICE" == "1" && -n "${PROJECT:-}" ]]; then
        BASE="$PROJECT"
    else
        [[ "$SCOPE_CHOICE" == "1" ]] && warn "No project selected yet — writing MCP config at user scope (HOME)."
        BASE="$HOME"
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
# Step 3b — offer the Claude Code plugin FIRST (best-effort, non-fatal).
# Recommended path: free session summarization + the richest UX. Installing the
# plugin makes `mode: auto` pick the plugin's subagent engine live.
# -----------------------------------------------------------------------------
if command -v claude >/dev/null 2>&1; then
    if confirm "Install the BrainPalace Claude Code plugin? (recommended — free session summarization, richest UX)" "y"; then
        say "Installing plugin via Claude Code…"
        if timeout 120 claude plugins marketplace add bxw91/brainpalace </dev/tty >/dev/tty 2>&1 \
           && timeout 120 claude plugins install brainpalace@brainpalace-marketplace </dev/tty >/dev/tty 2>&1; then
            ok "Plugin installed."
            warn "Restart Claude Code (or start a new session) — plugin hooks + the chat-session-extractor agent load at session start."
        else
            warn "Plugin install did not complete. Install it later: 'claude plugins marketplace add bxw91/brainpalace && claude plugins install brainpalace@brainpalace-marketplace'. Continuing with CLI/provider setup."
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Step 4 — optional project setup (init + start + index). LAST step, opt-in.
# Inherits the global provider config written in Step 2.
# -----------------------------------------------------------------------------

step "Step 4/5 — Set up a project (optional)"

WATCH="off"
if confirm "Set up and index a project now?" "y"; then
    PROJECT="$(ask "Project root" "$PWD")"
    PROJECT="${PROJECT/#\~/$HOME}"
    [[ -d "$PROJECT" ]] || errx "Path does not exist: $PROJECT"
    PROJECT="$(cd "$PROJECT" && pwd)"
    say "Project: $PROJECT"

    WATCH_FLAG=""
    if confirm "Enable file watcher (auto reindex on save)?" "y"; then
        WATCH="auto"
        WATCH_FLAG="--watch auto"
    fi

    # init --start inherits the global provider config written in Step 2.
    say "Running: brainpalace init --start $WATCH_FLAG"
    (cd "$PROJECT" && "$AB_BIN" init --start $WATCH_FLAG) >/dev/tty
    ok "Server initialised and started."
    # init enables session summarization and auto-picks the engine (printed
    # above): plugin → subagent (free, Haiku); else → provider (your configured
    # AI). CLI-only? Installing the Claude Code plugin is cheaper (subscription),
    # or use a local Ollama summarizer to keep provider mode free + private.
    say "Session summarization: enabled (engine auto-picked; --no-extract to opt out)."

    if confirm "Index the project now?" "y"; then
        INDEX_PATH="$(ask "Path to index (relative to project root, or absolute)" ".")"
        CODE_FLAG=""
        confirm "Include code (AST chunking)? (no = docs only)" "y" || CODE_FLAG="--no-code"
        say "Running: brainpalace index $INDEX_PATH $CODE_FLAG"
        (cd "$PROJECT" && "$AB_BIN" index "$INDEX_PATH" $CODE_FLAG) >/dev/tty
        INDEXED_TARGET="$INDEX_PATH"
    else
        INDEXED_TARGET="skipped"
        warn "No index — queries return nothing until you run 'brainpalace index <path>'."
    fi
else
    PROJECT=""
    INDEXED_TARGET="skipped"
    say "No project set up — see the next steps after verification."
fi

# -----------------------------------------------------------------------------
# Step 5 — verify
# -----------------------------------------------------------------------------

step "Step 5/5 — Verify"

if [[ -n "$PROJECT" ]]; then
    (cd "$PROJECT" && "$AB_BIN" status) >/dev/tty || warn "status returned non-zero"

    if confirm "Run a sample query now?" "y"; then
        Q="$(ask "Query" "how does authentication work")"
        (cd "$PROJECT" && "$AB_BIN" query "$Q" --mode hybrid) >/dev/tty \
            || warn "Query failed — check provider config and index status."
    fi
else
    say "No project set up — skipping status/query checks."
    say "Global config: $(xdg_config_yaml)"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

cat >/dev/tty <<EOF

${c_gr}Setup complete.${c_reset}
  Binary:    $AB_BIN  ($("$AB_BIN" --version 2>/dev/null || echo "?"))
  Provider:  $PROVIDER (global — $(xdg_config_yaml))
  MCP wire:  $MCP_CLIENT
EOF

if [[ -n "$PROJECT" ]]; then
    cat >/dev/tty <<EOF
  Project:   $PROJECT
  Watcher:   $WATCH
  Indexed:   $INDEXED_TARGET

${c_bold}Next${c_reset} (auto-discovers the project from CWD):
  brainpalace status
  brainpalace query "..." --mode hybrid
EOF
else
    cat >/dev/tty <<EOF

${c_bold}Next${c_reset} — set up a project (the binary + provider are ready):

  cd /path/to/your/project
  brainpalace init
EOF
fi

cat >/dev/tty <<EOF

The provider is configured globally — every 'brainpalace init' inherits it.
Each project gets its own server on a separate auto-allocated port.
EOF
