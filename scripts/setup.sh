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
#   2. Decide chat-summary engine — offer the Claude Code plugin (free on the
#      subscription) BEFORE the provider wizard, so the wizard words the
#      summarization question correctly
#   3. Configure an embedding / summarisation provider GLOBALLY
#   4. Set up a project + wire your AI assistants (Claude / Codex / OpenCode /
#      Antigravity / skill-runtime skills, Qwen Code / Kimi CLI — skills +
#      MCP — plus MCP editors — Cursor / Windsurf / VS Code / Kilo / Cline —
#      via `install-mcp --client`)
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
    echo "    curl -sSL <url>/setup.sh -o /tmp/bp-setup.sh && bash /tmp/bp-setup.sh" >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# Helpers (all I/O via /dev/tty so curl | bash works)
# -----------------------------------------------------------------------------

c_bold=$(printf '\033[1m');     c_reset=$(printf '\033[0m')
c_cyan=$(printf '\033[1;36m');  c_yel=$(printf '\033[1;33m')
c_red=$(printf '\033[1;31m');   c_gr=$(printf '\033[1;32m')
c_dim=$(printf '\033[2m')

say()  { printf '%s==>%s %s\n' "$c_bold" "$c_reset" "$*" >/dev/tty; }
step() { printf '\n%s--- %s ---%s\n' "$c_cyan" "$*" "$c_reset" >/dev/tty; }
warn() { printf '%sWARN:%s %s\n' "$c_yel" "$c_reset" "$*" >/dev/tty; }
ok()   { printf '%s%s%s\n' "$c_gr" "$*" "$c_reset" >/dev/tty; }
errx() { printf '%sERROR:%s %s\n' "$c_red" "$c_reset" "$*" >/dev/tty; exit 2; }

# _box <color> <full> <title> <line>... — draw a titled box in <color> around the
# given lines so an action/result stands out from the surrounding `==>` log. The
# title (may be empty) is embedded in the top border and inherits the border
# color. <full>=1 stretches the box to the terminal width so it matches the
# full-width Rich panels the CLI's `install-agent` prints for the other tools;
# <full>=0 sizes it to its content. Lines must be plain ASCII (no embedded ANSI,
# no multi-byte) so their byte length matches the padded column width.
_box() {
    local color="$1" full="$2" title="$3"; shift 3
    local line maxw=0
    for line in "$@"; do (( ${#line} > maxw )) && maxw=${#line}; done
    # Widen so a "─ title ─…" top border always fits (leaves ≥1 trailing dash).
    (( ${#title} + 2 > maxw )) && maxw=$(( ${#title} + 2 ))
    if [[ "$full" == "1" ]]; then
        # Fill the terminal: content width = columns - 4 (the "│ " … " │" frame).
        local cols target
        cols="$(stty size </dev/tty 2>/dev/null | awk '{print $2}')"
        [[ "$cols" =~ ^[0-9]+$ ]] || cols="${COLUMNS:-100}"
        target=$(( cols - 4 ))
        (( target > maxw )) && maxw=$target
    fi
    local inner=$(( maxw + 2 )) top
    if [[ -n "$title" ]]; then
        local dashes=$(( inner - ${#title} - 3 ))
        (( dashes < 0 )) && dashes=0
        top="$(printf '─ %s ' "$title")$(printf '─%.0s' $(seq 1 "$dashes"))"
    else
        top="$(printf '─%.0s' $(seq 1 "$inner"))"
    fi
    printf '%s┌%s┐%s\n' "$color" "$top" "$c_reset" >/dev/tty
    for line in "$@"; do
        printf '%s│%s %-*s %s│%s\n' "$color" "$c_reset" "$maxw" "$line" "$color" "$c_reset" >/dev/tty
    done
    printf '%s└%s┘%s\n' "$color" "$(printf '─%.0s' $(seq 1 "$inner"))" "$c_reset" >/dev/tty
}

# box_red <line>...            — compact untitled red box (manual-command / error callouts).
# box_green <title> <line>...  — full-width titled green box (success / install steps),
#                                matching the CLI's full-width tool panels.
box_red()   { _box "$c_red" 0 "" "$@"; }
box_green() { _box "$c_gr" 1 "$@"; }

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

stop_all_brainpalace() {
    # Gracefully stop EVERY running BrainPalace server + the dashboard using the
    # currently-installed binary, BEFORE its pipx venv gets replaced. A live
    # server still holding the old venv/code can clash with the reinstall.
    # Best-effort, never fatal. No jq dependency — pull roots out of list --json.
    # Each stopped root is recorded in the global STOPPED_ROOTS so the end of the
    # script can offer to restart them on the freshly-installed version.
    local bin="$1" roots root any=0
    if roots="$("$bin" list --json 2>/dev/null)"; then
        while IFS= read -r root; do
            [[ -z "$root" ]] && continue
            say "stopping server: $root"
            "$bin" stop --path "$root" >/dev/tty 2>&1 || true
            STOPPED_ROOTS+=("$root")
            any=1
        done < <(printf '%s' "$roots" \
            | grep -oE '"project_root"[[:space:]]*:[[:space:]]*"[^"]+"' \
            | sed -E 's/.*"([^"]*)"$/\1/')
    fi
    say "stopping dashboard"
    "$bin" dashboard stop >/dev/tty 2>&1 || true
    if [[ "$any" -eq 1 ]]; then
        ok "All BrainPalace servers + dashboard stopped."
    else
        say "No tracked servers were running; dashboard reaped if present."
    fi
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

pick_multi() {
    # pick_multi "Prompt" "label1" "label2" ...
    # Like pick, but accepts comma-separated indices (e.g. "1,3") so more than
    # one option can be chosen in a single answer. Invalid tokens (blank,
    # non-numeric, out of range) are warned about and skipped rather than
    # aborting the whole selection. Prints the valid chosen indices
    # space-separated to stdout (empty string if none chosen).
    local prompt="$1"; shift
    local i=1
    for opt in "$@"; do
        printf '   %d) %s\n' "$i" "$opt" >/dev/tty
        i=$((i+1))
    done
    local n=$#
    local raw
    raw="$(ask "$prompt" "")"
    local -a toks=() chosen=()
    IFS=',' read -ra toks <<< "$raw" || true
    local tok
    for tok in "${toks[@]:-}"; do
        tok="${tok//[[:space:]]/}"
        [[ -z "$tok" ]] && continue
        if ! [[ "$tok" =~ ^[0-9]+$ ]] || (( tok < 1 || tok > n )); then
            warn "Invalid choice '$tok' — skipping."
            continue
        fi
        chosen+=("$tok")
    done
    printf '%s' "${chosen[*]:-}"
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
  2. Chat summaries — Claude Code plugin (free on your subscription)
  3. Configure provider globally
  4. Set up a project + wire your AI assistants (optional)
  5. Verify

EOF
confirm "Continue?" "y" || { say "Aborted."; exit 0; }

# -----------------------------------------------------------------------------
# Prerequisite awareness — report Python / pipx / git status and the dashboard's
# Python 3.12+ requirement BEFORE installing, so the user knows what's missing.
# Fatal only on Python < 3.10 (nothing runs without it); the rest are advisory.
# -----------------------------------------------------------------------------
check_prereqs() {
    step "Prerequisites"
    local summary=""
    if command -v python3 >/dev/null 2>&1; then
        local py_ver py_major py_minor
        py_ver="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")"
        py_major="${py_ver%%.*}"; py_minor="${py_ver##*.}"
        if [[ -n "$py_ver" ]] && { (( py_major > 3 )) || { (( py_major == 3 )) && (( py_minor >= 10 )); }; }; then
            summary="Python : $py_ver detected."
            if (( py_major == 3 && py_minor < 12 )); then
                warn "Python < 3.12: the web dashboard is skipped (CLI + server still work fully). Install Python 3.12+ for the best experience (dashboard included)."
            else
                summary="$summary Web dashboard : available."
            fi
        else
            errx "Python ${py_ver:-?} found, but BrainPalace needs Python 3.10+ (3.12+ for the dashboard). Install a newer Python and re-run."
        fi
    else
        errx "python3 not found — BrainPalace needs Python 3.10+ (3.12+ for the dashboard)."
    fi

    if command -v pipx >/dev/null 2>&1; then
        summary="$summary PIPX: present."
    else
        warn "pipx not found — used for the isolated CLI install. Install: 'apt install pipx' (or 'brew install pipx'), then 'pipx ensurepath'."
    fi

    if command -v git >/dev/null 2>&1; then
        summary="$summary GIT: present."
    else
        warn "git not found — only needed to install from a local source checkout (PyPI installs do not need it)."
    fi

    [[ -n "$summary" ]] && ok "$summary"
    say "One embedding provider is required: a cloud API key OR a local Ollama with an embedding model pulled."
}

check_prereqs

# -----------------------------------------------------------------------------
# Step 1 — install
# -----------------------------------------------------------------------------

step "Step 1/5 — Install brainpalace binary"

# Project roots whose servers we stop for the upgrade (populated by
# stop_all_brainpalace). The final step offers to restart them on the new build.
STOPPED_ROOTS=()

# Did brainpalace already exist on this machine BEFORE this run? Captured now,
# before any install, so the assistant menu can note that new selections add to
# tools wired by an earlier BrainPalace install (gates that note in Step 4).
BP_PREEXISTING=""
command -v brainpalace >/dev/null 2>&1 && BP_PREEXISTING=1

# Shut everything down FIRST — before we touch the venv. A running server (or
# dashboard) on the old code can clash with the reinstall, so ask up front.
if command -v brainpalace >/dev/null 2>&1; then
    if confirm "Stop all running BrainPalace servers and the dashboard before installing? (recommended)" "y"; then
        stop_all_brainpalace "$(command -v brainpalace)"
    else
        warn "Leaving running servers up — a live old-venv server can clash with the reinstall."
    fi
fi

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

    # Tell install.sh it runs inside guided setup so it suppresses its own
    # "Next steps" block — this script gives the (simpler) guidance at the end.
    export BRAINPALACE_GUIDED_SETUP=1
    if [[ -n "$USE_LOCAL" ]]; then
        bash "$USE_LOCAL/scripts/install.sh" --local "$USE_LOCAL" </dev/tty >/dev/tty
    else
        INSTALL_URL="${REPO_URL%.git}"
        INSTALL_URL="${INSTALL_URL/github.com/raw.githubusercontent.com}/${REF}/scripts/install.sh"
        # Pin the exact version we just detected on PyPI so install.sh installs
        # *that* release — not whatever pip's stale index cache resolves as
        # "latest", which can be the previous version right after a release.
        if [[ -n "$LATEST_CLI" ]]; then
            curl -sSL "$INSTALL_URL" | bash -s -- --version "$LATEST_CLI" >/dev/tty
        else
            curl -sSL "$INSTALL_URL" | bash >/dev/tty
        fi
    fi

    command -v brainpalace >/dev/null 2>&1 \
        || errx "'brainpalace' still not on PATH. Check pipx + 'pipx ensurepath'."
    ok "Installed: $(brainpalace --version)"
fi

BP_BIN="$(command -v brainpalace)"

# -----------------------------------------------------------------------------
# Step 2 — chat/session summaries (Claude Code plugin). Decided BEFORE the
# provider wizard so the wizard can word the summarization question correctly:
#   - plugin present/installed -> chat summaries are FREE on the Claude Code
#     subscription; the provider picked next is for CODE only.
#   - no plugin                -> chat summarization is OFF by default (the
#     server-side provider distiller is doubly opt-in: mode=provider/auto AND
#     SESSION_DISTILL_ENABLED=true); the provider is for CODE only.
# CHAT_SUMM is passed to every `config wizard --global` as --chat-summarizer
# (wording-only; the server still resolves the engine 'auto' at runtime).
# -----------------------------------------------------------------------------

step "Step 2/5 — Chat summaries"

CHAT_SUMM="provider"
if command -v claude >/dev/null 2>&1; then
    PLUGIN_INSTALLED="false"
    # Single source of truth: the CLI's own detection, surfaced as JSON.
    if PLUGIN_JSON="$("$BP_BIN" plugin status --json 2>/dev/null)"; then
        case "$PLUGIN_JSON" in
            *'"installed": true'*|*'"installed":true'*) PLUGIN_INSTALLED="true" ;;
        esac
    fi
    if [[ "$PLUGIN_INSTALLED" == "true" ]]; then
        CHAT_SUMM="plugin"
        # Surface installed-vs-latest plugin version (parity with the
        # `brainpalace update` tail). The version/latest/update_available keys are
        # already in the JSON we fetched above, so this adds no extra work. We
        # only PRINT the update command — driving `claude plugins …` from a
        # script can hang on its process scan, so Claude Code runs it itself.
        PLUGIN_VER="$(printf '%s' "$PLUGIN_JSON" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p')"
        PLUGIN_LATEST="$(printf '%s' "$PLUGIN_JSON" | sed -n 's/.*"latest": *"\([^"]*\)".*/\1/p')"
        if [[ -n "$PLUGIN_VER" ]]; then
            say "Claude Code plugin detected version: $PLUGIN_VER"
        else
            say "Claude Code plugin detected."
        fi
        case "$PLUGIN_JSON" in
            *'"update_available": true'*|*'"update_available":true'*)
                say "Plugin update available: ${PLUGIN_LATEST:-newer} — run this in your terminal:"
                box_red "claude plugin update brainpalace@brainpalace-marketplace"
                say "(then restart Claude Code to load the new plugin)."
                ;;
        esac
    else
        # We no longer install the plugin from here. Claude Code manages its own
        # plugins, and driving 'claude plugins …' from a script can hang on its
        # process scan. Leave the install to Claude Code itself.
        say "Claude Code plugin not installed. Install it from INSIDE Claude Code"
        say "(it manages its own plugins): run /plugin, add the marketplace"
        say "'bxw91/brainpalace', then install 'brainpalace'. Once it loads, chat/"
        say "session summaries run FREE on your Claude Code subscription."
        say "Until then chat summarization is OFF by default (opt in with"
        say "SESSION_DISTILL_ENABLED=true). The provider you pick next is for code only."
        say "(Step 4/5 can install the plugin for you automatically, if you'd rather not.)"
        CHAT_SUMM="provider"
    fi
else
    say "Claude CLI not found — chat/session summaries are handled by the Claude"
    say "Code plugin (free). Without it, chat summarization is OFF by default"
    say "(opt in with SESSION_DISTILL_ENABLED=true). The provider you pick next is"
    say "for code only. Install the plugin later for free chat summaries."
fi

# -----------------------------------------------------------------------------
# Step 3 — configure provider GLOBALLY (no project yet). Written to the XDG
# global config that every later `brainpalace init` inherits, so the project
# step can be deferred to the end and made optional.
# -----------------------------------------------------------------------------

step "Step 3/5 — Provider / API key (global)"

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
        (cd "$HOME" && "$BP_BIN" config wizard --global --chat-summarizer "$CHAT_SUMM") </dev/tty >/dev/tty
        ;;
    ollama)
        OLLAMA_URL="$(ask "Ollama base URL" "${OLLAMA_BASE_URL:-http://127.0.0.1:11434}")"
        if curl -fsS --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
            ok "Reached Ollama at $OLLAMA_URL"
        else
            warn "Could not reach $OLLAMA_URL — wizard will still let you continue."
        fi
        say "Launching wizard (global) with OLLAMA_BASE_URL=$OLLAMA_URL"
        (cd "$HOME" && OLLAMA_BASE_URL="$OLLAMA_URL" "$BP_BIN" config wizard --global --chat-summarizer "$CHAT_SUMM") </dev/tty >/dev/tty
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
        (cd "$HOME" && "$BP_BIN" config wizard --global --chat-summarizer "$CHAT_SUMM") </dev/tty >/dev/tty
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
    BP_PY="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null)/brainpalace-cli/bin/python"
    [[ -x "$BP_PY" ]] || BP_PY="python3"
    "$BP_PY" - "$CFG" <<'PY' >/dev/tty 2>&1 || warn "config.yaml api_key_env patch failed — set manually if you picked cohere/gemini/grok"
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
# Step 4 — optional project setup (init + start + index). LAST step, opt-in.
# Inherits the global provider config written in Step 3.
# -----------------------------------------------------------------------------

# plugin_installed — true when the Claude Code plugin is already installed.
# Uses the CLI's own detection surfaced as JSON (same source as Step 2), so it
# needs no `claude` binary and never drives Claude Code.
plugin_installed() {
    local j
    j="$("$BP_BIN" plugin status --json 2>/dev/null)" || return 1
    case "$j" in *'"installed": true'*|*'"installed":true'*) return 0 ;; esac
    return 1
}

install_claude_plugin() {
    # PRINT the plugin commands — never drive `claude plugins …` from the script.
    # Driving it hangs: `marketplace add` git-clones over HTTPS (an interactive
    # auth prompt when the keyring is locked) and `plugins install` blocks on its
    # process/trust scan, with no way to Ctrl+C out (same reason Step 3 only
    # prints). We detect install state and show only the relevant box. Framing
    # differs by surface: `claude plugin update` is a TERMINAL command (the
    # `claude` binary), whereas `/plugin …` are slash commands run INSIDE the
    # Claude Code REPL — so each branch says where its command runs.
    if plugin_installed; then
        local pstate lines=()
        pstate="$(printf '%s' "$("$BP_BIN" plugin status 2>&1 || true)" | sed -n 's/^BrainPalace Claude Code plugin: //p' | head -1)"
        [[ -n "$pstate" ]] && lines+=("Plugin: $pstate" "")
        # Self-contained box: says WHAT to do, WHERE to run it, then a blank line
        # before the copy-paste command so it stands out.
        lines+=(
            "Update available. Update the plugin, then restart Claude Code."
            "Run this in your TERMINAL (qualified name - the bare name fails):"
            ""
            "claude plugin update brainpalace@brainpalace-marketplace"
        )
        box_green "Claude Code" "${lines[@]}"
    else
        box_green "Claude Code" \
            "Plugin not installed. Run these INSIDE Claude Code (it manages its" \
            "own plugins; chat/session summaries then run FREE on your plan):" \
            "" \
            "/plugin marketplace add bxw91/brainpalace" \
            "/plugin install brainpalace"
    fi
    return 0
}

# Assistant / runtime catalogue — shared by the project and no-project paths.
# claude = plugin (printed /plugin commands, run inside Claude Code);
# codex/opencode/antigravity/skill-runtime
# = skills via install-agent; cursor/windsurf/vscode/kilo/cline = MCP config via
# install-mcp --client (the single, merge-safe writer — no hand-rolled overwrite).
ASSISTANT_KEYS=(claude codex opencode antigravity skill-runtime qwen kimi cursor windsurf vscode kilo cline)
declare -A ASSISTANT_LABEL=(
    [claude]="Claude Code           — prints the /plugin install commands (run inside Claude Code)"
    [codex]="Codex                 — .codex/skills/brainpalace + AGENTS.md"
    [opencode]="OpenCode              — .opencode/plugins/brainpalace"
    [antigravity]="Antigravity (agy)     — .agents/skills/brainpalace + AGENTS.md"
    [skill-runtime]="Generic skill-runtime — writes SKILL.md files to a directory you choose"
    [qwen]="Qwen Code — skills + MCP"
    [kimi]="Kimi CLI — skills + MCP"
    [cursor]="Cursor                — MCP config (install-mcp --client cursor)"
    [windsurf]="Windsurf              — MCP config (install-mcp --client windsurf)"
    [vscode]="GitHub Copilot/VS Code — MCP config (install-mcp --client vscode)"
    [kilo]="Kilo Code             — MCP config (install-mcp --client kilo)"
    [cline]="Cline                 — MCP config (install-mcp --client cline)"
)

# _vscode_ext_present <substr>... — echo the path of the first installed VS Code
# extension whose directory name contains one of the substrings (VS Code, OSS,
# and server dirs) and return 0; return 1 if none. Used for editor-extension
# assistants (Kilo, Cline) that ship no PATH binary.
_vscode_ext_present() {
    local d pat hit
    for d in "$HOME/.vscode/extensions" "$HOME/.vscode-oss/extensions" \
             "$HOME/.vscode-server/extensions" "$HOME/.cursor/extensions"; do
        [[ -d "$d" ]] || continue
        for pat in "$@"; do
            hit="$(compgen -G "$d/*${pat}*" 2>/dev/null | head -1)" || true
            [[ -n "$hit" ]] && { printf '%s\n' "$hit"; return 0; }
        done
    done
    return 1
}

# _bin_path <name>... — echo the PATH of the first binary that resolves and
# return 0; return 1 if none resolve.
_bin_path() {
    local b
    for b in "$@"; do
        command -v "$b" 2>/dev/null && return 0
    done
    return 1
}

# _dir_path <dir>... — echo the first existing directory and return 0; else 1.
_dir_path() {
    local d
    for d in "$@"; do
        [[ -d "$d" ]] && { printf '%s\n' "$d"; return 0; }
    done
    return 1
}

# assistant_detected <key> — best-effort: is this tool present on the machine?
# On a hit, ECHOES the location it was found at (a CLI on PATH, or a well-known
# config/home dir — covers GUI editors with no PATH binary) and returns 0; on a
# miss echoes nothing and returns 1. skill-runtime is a generic "pick a
# directory" target — never auto-detected. Non-fatal: a miss just means the
# name is neither highlighted nor annotated with a location.
assistant_detected() {
    case "$1" in
        claude)       _bin_path claude          || _dir_path "$HOME/.claude" ;;
        codex)        _bin_path codex           || _dir_path "$HOME/.codex" ;;
        opencode)     _bin_path opencode        || _dir_path "$HOME/.opencode" "$HOME/.config/opencode" ;;
        antigravity)  _bin_path agy antigravity || _dir_path "$HOME/.antigravity" "$HOME/.agents" ;;
        qwen)         _bin_path qwen            || _dir_path "$HOME/.qwen" ;;
        kimi)         _bin_path kimi            || _dir_path "$HOME/.kimi" ;;
        cursor)       _bin_path cursor          || _dir_path "$HOME/.cursor" "$HOME/.config/Cursor" "$HOME/Library/Application Support/Cursor" ;;
        windsurf)     _bin_path windsurf        || _dir_path "$HOME/.codeium/windsurf" "$HOME/.config/Windsurf" "$HOME/Library/Application Support/Windsurf" ;;
        vscode)       _bin_path code            || _dir_path "$HOME/.vscode" "$HOME/.config/Code" "$HOME/Library/Application Support/Code" ;;
        kilo)         _vscode_ext_present kilocode kilo-code ;;
        cline)        _vscode_ext_present saoudrizwan.claude-dev cline ;;
        *)            return 1 ;;
    esac
}

# choose_assistants -> echoes the picked index list (space-separated) | "".
# Tools detected on this machine are highlighted green (name only) and get a
# dim sub-line naming WHERE they were found, printed under the tool.
choose_assistants() {
    local labels=() a_key lbl name rest loc
    for a_key in "${ASSISTANT_KEYS[@]}"; do
        lbl="${ASSISTANT_LABEL[$a_key]}"
        if loc="$(assistant_detected "$a_key")"; then
            # Color only the tool name — everything up to the em-dash separator.
            # Trailing pad spaces are zero-width, so column alignment is kept.
            name="${lbl%%—*}"; rest="${lbl#"$name"}"
            lbl="${c_gr}${name}${c_reset}${rest}"
            # Append the detected location as an indented dim sub-line (embedded
            # newline; pick_multi prints the label verbatim, so it lands under
            # the tool name without its own list number).
            [[ -n "$loc" ]] && lbl="${lbl}"$'\n'"      ${c_dim}↳ found: ${loc}${c_reset}"
        fi
        labels+=("$lbl")
    done
    # Only when BrainPalace already existed on this machine before this run do
    # earlier wirings persist — so the "added to previous" note is relevant then.
    [[ -n "${BP_PREEXISTING:-}" ]] && \
        say "${c_dim}Selections are added to previously selected tools.${c_reset}"
    printf '\n' >/dev/tty   # blank line before the first tool in the list
    pick_multi "Assistants (comma-separated, e.g. 1,3; blank for none)" "${labels[@]}"
}

# _in_dir <dir> cmd... — run cmd in <dir> (subshell) when non-empty, else in CWD;
# output to the tty either way.
_in_dir() {
    local d="$1"; shift
    if [[ -n "$d" ]]; then (cd "$d" && "$@") >/dev/tty; else "$@" >/dev/tty; fi
}

# execute_wirings <picked_idx> — wire each picked assistant. Uses the global
# PROJECT (may be empty); project-scoped skills fall back to --global when there
# is no project. Appends each success to WIRED_ASSISTANTS.
execute_wirings() {
    local picked="$1" a_idx RUNTIME
    if [[ -z "$picked" ]]; then say "No assistants wired."; return; fi
    for a_idx in $picked; do
        RUNTIME="${ASSISTANT_KEYS[$((a_idx-1))]:-}"
        case "$RUNTIME" in
            claude)
                install_claude_plugin
                WIRED_ASSISTANTS+=("claude (run /plugin inside Claude Code)")
                ;;
            skill-runtime)
                local skill_dir
                skill_dir="$(ask "Target directory for skill-runtime SKILL.md files" "${PROJECT:-$HOME}/.skills/brainpalace")"
                # install-agent prints its own titled panel (name + target dir).
                if _in_dir "$PROJECT" "$BP_BIN" install-agent --agent skill-runtime --dir "$skill_dir"; then
                    WIRED_ASSISTANTS+=("skill-runtime")
                else
                    warn "skill-runtime: install-agent failed — run manually:"
                    box_red "brainpalace install-agent --agent skill-runtime --dir $skill_dir"
                fi
                ;;
            cursor|windsurf|vscode|kilo|cline)
                # install-mcp prints its own titled panel (tool name + target).
                if _in_dir "$PROJECT" "$BP_BIN" install-mcp --client "$RUNTIME"; then
                    WIRED_ASSISTANTS+=("$RUNTIME")
                else
                    warn "$RUNTIME: install-mcp failed — run manually:"
                    box_red "brainpalace install-mcp --client $RUNTIME"
                fi
                ;;
            codex|opencode|antigravity)
                local gflag=()
                [[ -z "$PROJECT" ]] && gflag=(--global)
                # install-agent prints its own titled result panel (tool name +
                # scope), so we don't echo a duplicate status line here.
                if _in_dir "$PROJECT" "$BP_BIN" install-agent --agent "$RUNTIME" "${gflag[@]}"; then
                    WIRED_ASSISTANTS+=("$RUNTIME")
                else
                    warn "$RUNTIME: install-agent failed — run manually:"
                    box_red "brainpalace install-agent --agent $RUNTIME"
                fi
                ;;
            qwen|kimi)
                # Dual wiring: skills (install-agent) AND MCP (install-mcp
                # --client), which shipped for qwen/kimi in Phase B. Each half
                # is independently non-fatal — one can fail without aborting
                # the other or the rest of the loop.
                local gflag=()
                [[ -z "$PROJECT" ]] && gflag=(--global)
                # skills: install-agent prints its own titled panel — no dup line.
                if _in_dir "$PROJECT" "$BP_BIN" install-agent --agent "$RUNTIME" "${gflag[@]}"; then
                    WIRED_ASSISTANTS+=("$RUNTIME (skills)")
                else
                    warn "$RUNTIME: install-agent failed — run manually:"
                    box_red "brainpalace install-agent --agent $RUNTIME"
                fi
                # mcp: install-mcp prints its own titled panel — no dup line.
                if _in_dir "$PROJECT" "$BP_BIN" install-mcp --client "$RUNTIME"; then
                    WIRED_ASSISTANTS+=("$RUNTIME (mcp)")
                else
                    warn "$RUNTIME: install-mcp failed — run manually:"
                    box_red "brainpalace install-mcp --client $RUNTIME"
                fi
                ;;
        esac
    done
}

step "Step 4/5 — Set up a project (optional)"

WATCH="off"
WIRED_ASSISTANTS=()
if confirm "Set up and index a project now?" "n"; then
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

    # -------------------------------------------------------------------
    # Choose assistants BEFORE init, so init knows whether to wire Claude
    # Code's MCP. The catalogue + wiring live in choose_assistants /
    # execute_wirings (defined above) so the no-project path reuses them.
    # -------------------------------------------------------------------
    echo >/dev/tty
    say "Wire AI coding assistants for this project?"
    PICKED_IDX="$(choose_assistants)"

    # Decide init's Claude Code integration. Root .mcp.json AND the ~/.claude
    # SessionStart hook are read only by Claude Code, so wire them only when the
    # user actually PICKED Claude this run; otherwise pass --no-mcp so a project
    # wired for other tools gets no stray Claude .mcp.json/hook. (Merely having
    # the `claude` CLI installed no longer counts — pick it to wire it. Existing
    # Claude wiring from a prior run is left untouched; this only gates new writes.)
    CLAUDE_PICKED=""
    for a_idx in $PICKED_IDX; do
        [[ "${ASSISTANT_KEYS[$((a_idx-1))]:-}" == "claude" ]] && CLAUDE_PICKED="1"
    done
    MCP_FLAG=""
    if [[ -z "$CLAUDE_PICKED" ]]; then
        MCP_FLAG="--no-mcp"
        say "Claude Code not selected — init will skip Claude MCP + hook wiring (--no-mcp)."
    fi

    # init --start inherits the global provider config written in Step 3.
    say "Running: brainpalace init --start $WATCH_FLAG $MCP_FLAG"
    (cd "$PROJECT" && "$BP_BIN" init --start $WATCH_FLAG $MCP_FLAG) >/dev/tty
    ok "Server initialised and started."

    # Wire the picked assistants now that PROJECT is init'd.
    execute_wirings "$PICKED_IDX"

    if confirm "Index the project now?" "y"; then
        INDEX_PATH="$(ask "Path to index (relative to project root, or absolute)" ".")"
        CODE_FLAG=""
        confirm "Include code (AST chunking)? (no = docs only)" "y" || CODE_FLAG="--no-code"
        say "Running: brainpalace index $INDEX_PATH $CODE_FLAG"
        (cd "$PROJECT" && "$BP_BIN" index "$INDEX_PATH" $CODE_FLAG) >/dev/tty
        INDEXED_TARGET="$INDEX_PATH"
    else
        INDEXED_TARGET="skipped"
        warn "No index — queries return nothing until you run 'brainpalace index <path>'."
    fi
else
    PROJECT=""
    INDEXED_TARGET="skipped"
    say "No project set up — you can still wire assistants globally."
    echo >/dev/tty
    say "Wire AI coding assistants now (global scope — no project needed)?"
    execute_wirings "$(choose_assistants)"
fi

# -----------------------------------------------------------------------------
# Step 6 — verify
# -----------------------------------------------------------------------------

step "Step 5/5 — Verify"

if [[ -n "$PROJECT" ]]; then
    (cd "$PROJECT" && "$BP_BIN" status) >/dev/tty || warn "status returned non-zero"

    if confirm "Run a sample query now?" "y"; then
        Q="$(ask "Query" "how does authentication work")"
        (cd "$PROJECT" && "$BP_BIN" query "$Q" --mode hybrid) >/dev/tty \
            || warn "Query failed — check provider config and index status."
    fi
fi

# -----------------------------------------------------------------------------
# Restart previously-running servers
#
# Step 1 stopped every running server (and the dashboard) so the pipx venv could
# be swapped safely — but it never brought them back. Restart each one on the
# freshly-installed version, behind a single confirm, so an upgrade restores the
# prior running state instead of silently leaving every project down. The one
# project Step 4 just started (if any) is skipped — it is already up — and the
# dashboard autostarts with the first restart.
# -----------------------------------------------------------------------------

if (( ${#STOPPED_ROOTS[@]} > 0 )); then
    RESTART_ROOTS=()
    for root in "${STOPPED_ROOTS[@]}"; do
        [[ -n "$PROJECT" && "$root" == "$PROJECT" ]] && continue  # already started
        RESTART_ROOTS+=("$root")
    done
    if (( ${#RESTART_ROOTS[@]} > 0 )); then
        step "Restart previously-running servers"
        say "These servers were stopped for the upgrade:"
        for root in "${RESTART_ROOTS[@]}"; do say "  $root"; done
        if confirm "Restart them now (on the new version)?" "y"; then
            for root in "${RESTART_ROOTS[@]}"; do
                if [[ -d "$root" ]]; then
                    say "Starting: $root"
                    "$BP_BIN" start --path "$root" >/dev/tty 2>&1 \
                        || warn "Could not restart $root — start it manually with 'brainpalace start'."
                else
                    warn "Skipping $root — directory no longer exists."
                fi
            done
        else
            say "Left stopped — restart any later with 'brainpalace start' in the project."
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

# Dashboard install/run state — the "not installed" hint is the reliable signal
# (status exit codes don't distinguish absent-package from stopped).
DASH_RAW="$("$BP_BIN" dashboard status 2>&1 || true)"
case "$DASH_RAW" in
    *"not installed"*)     DASH_LINE="not installed (Python < 3.12?)" ;;
    *"Dashboard running"*) DASH_LINE="installed (running)" ;;
    *)                     DASH_LINE="installed (stopped)" ;;
esac
cat >/dev/tty <<EOF

${c_gr}Setup complete.${c_reset}
  Binary:    $BP_BIN  ($("$BP_BIN" --version 2>/dev/null || echo "?"))
  Provider:  $PROVIDER (global — $(xdg_config_yaml))
  Dashboard: $DASH_LINE
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

BrainPalace is configured globally. To index your project:
  cd /path/to/your/project
  brainpalace init
EOF
fi
