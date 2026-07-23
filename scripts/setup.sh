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

say()  { printf '%s==>%s %s\n' "$c_bold" "$c_reset" "$*" >/dev/tty; }
step() { printf '\n%s--- %s ---%s\n' "$c_cyan" "$*" "$c_reset" >/dev/tty; }
warn() { printf '%sWARN:%s %s\n' "$c_yel" "$c_reset" "$*" >/dev/tty; }
ok()   { printf '%s%s%s\n' "$c_gr" "$*" "$c_reset" >/dev/tty; }
errx() { printf '%sERROR:%s %s\n' "$c_red" "$c_reset" "$*" >/dev/tty; exit 2; }

# box_red "line" ["line" ...] — draw a red-bordered box around the given lines so
# an action the user must run by hand (e.g. the plugin update command) stands out
# from the surrounding `==>` log. Lines must be plain (no embedded ANSI) so the
# byte length matches the rendered width.
box_red() {
    local line maxw=0
    for line in "$@"; do (( ${#line} > maxw )) && maxw=${#line}; done
    local border; border=$(printf '─%.0s' $(seq 1 $((maxw + 2))))
    printf '%s┌%s┐%s\n' "$c_red" "$border" "$c_reset" >/dev/tty
    for line in "$@"; do
        printf '%s│%s %-*s %s│%s\n' "$c_red" "$c_reset" "$maxw" "$line" "$c_red" "$c_reset" >/dev/tty
    done
    printf '%s└%s┘%s\n' "$c_red" "$border" "$c_reset" >/dev/tty
}

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
    local bin="$1" roots root any=0
    if roots="$("$bin" list --json 2>/dev/null)"; then
        while IFS= read -r root; do
            [[ -z "$root" ]] && continue
            say "stopping server: $root"
            "$bin" stop --path "$root" >/dev/tty 2>&1 || true
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
    if command -v python3 >/dev/null 2>&1; then
        local py_ver py_major py_minor
        py_ver="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")"
        py_major="${py_ver%%.*}"; py_minor="${py_ver##*.}"
        if [[ -n "$py_ver" ]] && { (( py_major > 3 )) || { (( py_major == 3 )) && (( py_minor >= 10 )); }; }; then
            ok "Python $py_ver detected (3.10+ required)."
            if (( py_major == 3 && py_minor < 12 )); then
                warn "Python < 3.12: the web dashboard is skipped (CLI + server still work fully). Install Python 3.12+ for the best experience (dashboard included)."
            else
                ok "Python >= 3.12: the web dashboard is available."
            fi
        else
            errx "Python ${py_ver:-?} found, but BrainPalace needs Python 3.10+ (3.12+ for the dashboard). Install a newer Python and re-run."
        fi
    else
        errx "python3 not found — BrainPalace needs Python 3.10+ (3.12+ for the dashboard)."
    fi

    if command -v pipx >/dev/null 2>&1; then
        ok "pipx present."
    else
        warn "pipx not found — used for the isolated CLI install. Install: 'apt install pipx' (or 'brew install pipx'), then 'pipx ensurepath'."
    fi

    if command -v git >/dev/null 2>&1; then
        ok "git present."
    else
        warn "git not found — only needed to install from a local source checkout (PyPI installs do not need it)."
    fi

    say "One embedding provider is required: a cloud API key (OpenAI / Anthropic / Cohere / Gemini / Grok) OR a local Ollama with an embedding model pulled. You configure this in Step 3."
}

check_prereqs

# -----------------------------------------------------------------------------
# Step 1 — install
# -----------------------------------------------------------------------------

step "Step 1/5 — Install brainpalace binary"

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

step "Step 2/5 — Chat summaries (Claude Code plugin)"

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
        say "Claude Code plugin detected — chat/session summaries run FREE on your"
        say "Claude Code subscription. The provider you pick next is for code only."
        CHAT_SUMM="plugin"
        # Surface installed-vs-latest plugin version (parity with the
        # `brainpalace update` tail). The version/latest/update_available keys are
        # already in the JSON we fetched above, so this adds no extra work. We
        # only PRINT the update command — driving `claude plugins …` from a
        # script can hang on its process scan, so Claude Code runs it itself.
        PLUGIN_VER="$(printf '%s' "$PLUGIN_JSON" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p')"
        PLUGIN_LATEST="$(printf '%s' "$PLUGIN_JSON" | sed -n 's/.*"latest": *"\([^"]*\)".*/\1/p')"
        [[ -n "$PLUGIN_VER" ]] && say "Plugin version: $PLUGIN_VER"
        case "$PLUGIN_JSON" in
            *'"update_available": true'*|*'"update_available":true'*)
                say "Plugin update available: ${PLUGIN_LATEST:-newer} — run this inside Claude Code:"
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

install_claude_plugin() {
    # PRINT the plugin-install commands — never drive `claude plugins …` from the
    # script. Driving it hangs: `marketplace add` git-clones over HTTPS (an
    # interactive auth prompt when the keyring is locked) and `plugins install`
    # blocks on its process/trust scan, with no way to Ctrl+C out (same reason
    # Step 3 only prints — see the plugin-not-installed branch above). Claude Code
    # manages its own plugins, so the user runs these from INSIDE Claude Code.
    say "Claude Code plugin: run these from INSIDE Claude Code to install it"
    say "(it manages its own plugins; chat/session summaries then run FREE):"
    box_red "/plugin marketplace add bxw91/brainpalace" \
            "/plugin install brainpalace"
    say "Already installed? Update with the QUALIFIED name (bare name fails):"
    box_red "claude plugin update brainpalace@brainpalace-marketplace"
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

# choose_assistants -> echoes the picked index list (space-separated) | "".
choose_assistants() {
    local labels=() a_key
    for a_key in "${ASSISTANT_KEYS[@]}"; do labels+=("${ASSISTANT_LABEL[$a_key]}"); done
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
                if _in_dir "$PROJECT" "$BP_BIN" install-agent --agent skill-runtime --dir "$skill_dir"; then
                    ok "skill-runtime: installed to $skill_dir."; WIRED_ASSISTANTS+=("skill-runtime")
                else
                    warn "skill-runtime: install-agent failed — run manually:"
                    box_red "brainpalace install-agent --agent skill-runtime --dir $skill_dir"
                fi
                ;;
            cursor|windsurf|vscode|kilo|cline)
                if _in_dir "$PROJECT" "$BP_BIN" install-mcp --client "$RUNTIME"; then
                    ok "$RUNTIME: MCP config written."; WIRED_ASSISTANTS+=("$RUNTIME")
                else
                    warn "$RUNTIME: install-mcp failed — run manually:"
                    box_red "brainpalace install-mcp --client $RUNTIME"
                fi
                ;;
            codex|opencode|antigravity)
                local gflag=() where="project"
                [[ -z "$PROJECT" ]] && { gflag=(--global); where="global"; }
                if _in_dir "$PROJECT" "$BP_BIN" install-agent --agent "$RUNTIME" "${gflag[@]}"; then
                    ok "$RUNTIME: installed ($where scope)."; WIRED_ASSISTANTS+=("$RUNTIME")
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
                local gflag=() where="project"
                [[ -z "$PROJECT" ]] && { gflag=(--global); where="global"; }
                if _in_dir "$PROJECT" "$BP_BIN" install-agent --agent "$RUNTIME" "${gflag[@]}"; then
                    ok "$RUNTIME: skills installed ($where scope)."; WIRED_ASSISTANTS+=("$RUNTIME (skills)")
                else
                    warn "$RUNTIME: install-agent failed — run manually:"
                    box_red "brainpalace install-agent --agent $RUNTIME"
                fi
                if _in_dir "$PROJECT" "$BP_BIN" install-mcp --client "$RUNTIME"; then
                    ok "$RUNTIME: MCP config written."; WIRED_ASSISTANTS+=("$RUNTIME (mcp)")
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

    # Decide init's MCP wiring. Claude Code MCP (.mcp.json + local-scope
    # register) is only useful when Claude Code is in play, so wire it when the
    # user picked Claude OR the `claude` CLI is already on PATH; otherwise pass
    # --no-mcp so a pure Codex/OpenCode/… project gets no stray Claude .mcp.json.
    CLAUDE_PICKED=""
    for a_idx in $PICKED_IDX; do
        [[ "${ASSISTANT_KEYS[$((a_idx-1))]:-}" == "claude" ]] && CLAUDE_PICKED="1"
    done
    MCP_FLAG=""
    if [[ -z "$CLAUDE_PICKED" ]] && ! command -v claude >/dev/null 2>&1; then
        MCP_FLAG="--no-mcp"
        say "Claude Code not detected and not selected — init will skip Claude MCP wiring (--no-mcp)."
    fi

    # init --start inherits the global provider config written in Step 3.
    say "Running: brainpalace init --start $WATCH_FLAG $MCP_FLAG"
    (cd "$PROJECT" && "$BP_BIN" init --start $WATCH_FLAG $MCP_FLAG) >/dev/tty
    ok "Server initialised and started."
    say "Session summarization: enabled (engine auto-picked; --no-extract to opt out)."
    say "  Chat summaries run after your FIRST prompt — in batches of up to 8 sessions (<=1 MB), 5-min cool-down (free Haiku subagent)."

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
    say "  Skills runtimes (codex/opencode/antigravity/qwen/kimi) install --global;"
    say "  MCP editors write their user-scope config; Claude installs its plugin."
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
else
    say "No project set up — skipping status/query checks."
    say "Global config: $(xdg_config_yaml)"
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
# Plugin install state + installed-vs-latest version, straight from the CLI's
# own `plugin status` (strip its label; blank -> unknown).
PLUGIN_RAW="$("$BP_BIN" plugin status 2>&1 || true)"
PLUGIN_LINE="$(printf '%s' "$PLUGIN_RAW" | sed -n 's/^BrainPalace Claude Code plugin: //p' | head -1)"
[[ -z "$PLUGIN_LINE" ]] && PLUGIN_LINE="unknown"

WIRED_LINE="(none)"
[[ ${#WIRED_ASSISTANTS[@]} -gt 0 ]] && WIRED_LINE="${WIRED_ASSISTANTS[*]}"

cat >/dev/tty <<EOF

${c_gr}Setup complete.${c_reset}
  Binary:    $BP_BIN  ($("$BP_BIN" --version 2>/dev/null || echo "?"))
  Provider:  $PROVIDER (global — $(xdg_config_yaml))
  Dashboard: $DASH_LINE
  Plugin:    $PLUGIN_LINE
  Wired:     $WIRED_LINE
EOF

# When the plugin line reports a newer version, repeat the update command in a
# red box here at the end so it survives a long install scroll and the user can
# act on it without hunting back up to Step 2.
case "$PLUGIN_LINE" in
    *available*)
        printf '\n' >/dev/tty
        say "Plugin update available — run this inside Claude Code:"
        box_red "claude plugin update brainpalace@brainpalace-marketplace"
        say "(then restart Claude Code to load the new plugin)."
        ;;
esac

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
