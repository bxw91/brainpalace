#!/usr/bin/env bash
# BrainPalace guided uninstall / teardown.
#
# Fully interactive. Every removal is a prompt. The mirror image of setup.sh.
# Run directly from the network:
#
#   curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/uninstall.sh | bash
#
# Or from a local checkout:
#
#   bash scripts/uninstall.sh
#
# Order matters — servers are stopped and projects/plugins/MCP entries are
# handled *while the binary still exists*, then the package is removed, then
# the leftover on-disk state. Steps:
#   1. Stop running servers                       (y/n)
#   2. Remove plugins from every runtime + scope  (y/n)
#   3. Remove the `brainpalace` entry from MCP client configs (surgical, y/n)
#   4. Uninstall the package (auto-detected manager, confirm)
#   5. Delete per-project .brainpalace/ state     (multi-select)
#   6. Delete global state (XDG + legacy dirs)    (y/n)
#   7. Shell rc / API keys — LEFT FOR THE USER (a key may be shared with other
#      projects; we only print guidance).
#
# This is a destructive script. It deletes index data and ARCHIVED RAW CHAT
# TRANSCRIPTS (which may contain secrets). Every delete is confirmed.
#
# Requires an interactive terminal (reads from /dev/tty). Exits with a clear
# error if stdin / tty is not attached.
set -uo pipefail   # NOTE: no -e — we want to continue past a failed sub-step.

# -----------------------------------------------------------------------------
# Pre-flight: must have a TTY
# -----------------------------------------------------------------------------

if [[ ! -e /dev/tty ]] || ! { : >/dev/tty; } 2>/dev/null; then
    echo "ERROR: this script is interactive and needs a terminal." >&2
    echo "If you piped through curl in a non-interactive shell, run:" >&2
    echo "    curl -sSL <url>/uninstall.sh -o /tmp/ab-uninstall.sh && bash /tmp/ab-uninstall.sh" >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# Helpers (all I/O via /dev/tty so curl | bash works) — same style as setup.sh
# -----------------------------------------------------------------------------

c_bold=$(printf '\033[1m');     c_reset=$(printf '\033[0m')
c_cyan=$(printf '\033[1;36m');  c_yel=$(printf '\033[1;33m')
c_red=$(printf '\033[1;31m');   c_gr=$(printf '\033[1;32m')

say()  { printf '%s==>%s %s\n' "$c_bold" "$c_reset" "$*" >/dev/tty; }
step() { printf '\n%s--- %s ---%s\n' "$c_cyan" "$*" "$c_reset" >/dev/tty; }
warn() { printf '%sWARN:%s %s\n' "$c_yel" "$c_reset" "$*" >/dev/tty; }
ok()   { printf '%s%s%s\n' "$c_gr" "$*" "$c_reset" >/dev/tty; }

confirm() {
    # confirm "Prompt" "y|n" -> exit 0 if yes
    local prompt="$1" default="${2:-n}" reply hint
    [[ "$default" == "y" ]] && hint="[Y/n]" || hint="[y/N]"
    printf '%s %s ' "$prompt" "$hint" >/dev/tty
    IFS= read -r reply </dev/tty || reply=""
    reply="${reply:-$default}"
    [[ "${reply,,}" == "y" || "${reply,,}" == "yes" ]]
}

# -----------------------------------------------------------------------------
# Resolve a python interpreter for JSON/YAML surgery. Prefer the brainpalace
# pipx venv (PyYAML guaranteed) *while it still exists*; fall back to python3.
# -----------------------------------------------------------------------------

AB_PY="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null)/brainpalace-cli/bin/python"
[[ -x "$AB_PY" ]] || AB_PY="$(command -v python3 || true)"

AB_BIN="$(command -v brainpalace || true)"

# -----------------------------------------------------------------------------
# Banner + capture the project list NOW (registry survives binary removal).
# -----------------------------------------------------------------------------

clear >/dev/tty 2>/dev/null || true
cat >/dev/tty <<EOF
${c_bold}BrainPalace — guided uninstall${c_reset}

This removes BrainPalace and (optionally) all its on-disk state. Every
deletion is confirmed. Seven steps; step 7 (shell rc) is left to you.

${c_yel}Heads up:${c_reset} per-project state includes ARCHIVED RAW CHAT TRANSCRIPTS,
which may contain secrets. Deletions are irreversible.

EOF
[[ -z "$AB_BIN" ]] && warn "'brainpalace' not on PATH — CLI-driven steps (stop/plugin/package) will be skipped; file cleanup still runs."
confirm "Continue?" "y" || { say "Aborted. Nothing changed."; exit 0; }

# Discover global state dirs (honour XDG overrides).
XDG_CFG="${XDG_CONFIG_HOME:-$HOME/.config}/brainpalace"
XDG_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/brainpalace"
XDG_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/brainpalace"
LEGACY_DIR="$HOME/.brainpalace"

# Registry is the canonical project tracker. Read its keys directly so this
# works even after the binary is gone.
REGISTRY=""
for cand in "$XDG_STATE/registry.json" "$LEGACY_DIR/registry.json"; do
    [[ -f "$cand" ]] && { REGISTRY="$cand"; break; }
done

# Collect candidate project roots (registry keys) into PROJECTS[].
declare -a PROJECTS=()
if [[ -n "$REGISTRY" && -n "$AB_PY" ]]; then
    while IFS= read -r line; do
        [[ -n "$line" ]] && PROJECTS+=("$line")
    done < <("$AB_PY" - "$REGISTRY" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
for k in (d or {}):
    print(k)
PY
)
fi

# -----------------------------------------------------------------------------
# Step 1 — Stop running servers
# -----------------------------------------------------------------------------

step "Step 1/7 — Stop running servers"

if [[ -n "$AB_BIN" ]]; then
    "$AB_BIN" list >/dev/tty 2>&1 || true
    if confirm "Stop all running BrainPalace servers?" "y"; then
        if [[ ${#PROJECTS[@]} -gt 0 ]]; then
            for p in "${PROJECTS[@]}"; do
                say "Stopping server for: $p"
                "$AB_BIN" stop --path "$p" >/dev/tty 2>&1 || warn "  (no live server / already stopped)"
            done
        else
            "$AB_BIN" stop >/dev/tty 2>&1 || warn "  (no live server for cwd)"
        fi
        ok "Servers stopped."
    else
        warn "Left servers running — they will be orphaned once the binary is removed."
    fi
else
    warn "Binary missing — cannot stop servers via CLI. Kill stray 'uvicorn' procs manually if any."
fi

# -----------------------------------------------------------------------------
# Step 2 — Remove plugins (every runtime + both scopes)
# -----------------------------------------------------------------------------

step "Step 2/7 — Remove plugins from AI runtimes"

# NOTE: there is no CLI to remove an installed plugin (`install-agent` only
# installs; `brainpalace uninstall` removes global *data*, not plugins). So we
# delete the known install dirs directly — for every runtime, both scopes
# (global + each project). Paths mirror install_agent.py INSTALL_DIRS.
declare -a PLUGIN_DIRS=(
    "$HOME/.claude/plugins/brainpalace"
    "$HOME/.config/opencode/plugins/brainpalace"
    "$HOME/.config/gemini/plugins/brainpalace"
    "$HOME/.codex/skills/brainpalace"
)
for p in "${PROJECTS[@]}"; do
    PLUGIN_DIRS+=(
        "$p/.claude/plugins/brainpalace"
        "$p/.opencode/plugins/brainpalace"
        "$p/.gemini/plugins/brainpalace"
        "$p/.codex/skills/brainpalace"
    )
done

declare -a FOUND_PLUGINS=()
for d in "${PLUGIN_DIRS[@]}"; do [[ -d "$d" ]] && FOUND_PLUGINS+=("$d"); done

if [[ ${#FOUND_PLUGINS[@]} -eq 0 ]]; then
    say "No installed plugin dirs found (checked claude/opencode/gemini/codex, global + known projects)."
else
    say "Found ${#FOUND_PLUGINS[@]} plugin dir(s):"
    for d in "${FOUND_PLUGINS[@]}"; do printf '     %s\n' "$d" >/dev/tty; done
    if confirm "Delete all of the above plugin dirs?" "y"; then
        for d in "${FOUND_PLUGINS[@]}"; do rm -rf "$d" && ok "  removed $d"; done
    else
        warn "Skipped plugin removal."
    fi
fi

# Claude Code MARKETPLACE plugin — managed by Claude Code's own registry
# (~/.claude/plugins/cache/<marketplace>/brainpalace, tracked in
# installed_plugins.json). We advise rather than delete: hand-removing the cache
# desyncs that registry.
CC_MARKET=()
if [[ -d "$HOME/.claude/plugins/cache" ]]; then
    while IFS= read -r d; do CC_MARKET+=("$d"); done \
        < <(find "$HOME/.claude/plugins/cache" -mindepth 2 -maxdepth 2 -type d -name brainpalace 2>/dev/null)
fi
if [[ ${#CC_MARKET[@]} -gt 0 ]]; then
    warn "Claude Code marketplace plugin detected (managed by Claude Code — not removed here):"
    for d in "${CC_MARKET[@]}"; do printf '     %s\n' "$d" >/dev/tty; done
    say "  To remove it, in Claude Code run:  /plugin   → uninstall \"brainpalace\""
    say "  (optionally also remove the \"brainpalace-marketplace\")."
    say "  Do NOT delete the cache dir by hand — it desyncs Claude Code's plugin registry."
fi

# -----------------------------------------------------------------------------
# Step 3 — Surgically remove the `brainpalace` entry from MCP client configs.
# Done BEFORE package removal so the pipx venv python (PyYAML) is still around.
# -----------------------------------------------------------------------------

step "Step 3/7 — Clean MCP client configs (surgical — keeps your other servers)"

# Bases to scan: every project root + $HOME (user-scope configs).
declare -a MCP_BASES=("$HOME")
for p in "${PROJECTS[@]}"; do MCP_BASES+=("$p"); done

if [[ -z "$AB_PY" ]]; then
    warn "No python available — skipping surgical MCP cleanup. Remove 'brainpalace' entries by hand:"
    warn "  .vscode/mcp.json .cursor/mcp.json .zed/settings.json .cline/mcp.json .continue/mcp.yaml .kilo/kilo.jsonc"
elif confirm "Scan configs and remove the 'brainpalace' MCP entry (backs up each file first)?" "y"; then
    for base in "${MCP_BASES[@]}"; do
        for spec in \
            "$base/.vscode/mcp.json:json:servers" \
            "$base/.cursor/mcp.json:json:mcpServers" \
            "$base/.cline/mcp.json:json:mcpServers" \
            "$base/.zed/settings.json:json:context_servers" \
            "$base/.continue/mcp.yaml:yaml:mcpServers" ; do
            f="${spec%%:*}"; rest="${spec#*:}"; kind="${rest%%:*}"; key="${rest##*:}"
            [[ -f "$f" ]] || continue
            "$AB_PY" - "$f" "$kind" "$key" <<'PY' >/dev/tty 2>&1
import json, sys, pathlib, time
path, kind, key = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
try:
    if kind == "yaml":
        try:
            import yaml
        except ImportError:
            print(f"  SKIP {path} (PyYAML missing)"); sys.exit(0)
        data = yaml.safe_load(path.read_text()) or {}
    else:
        data = json.loads(path.read_text())
except Exception as e:
    print(f"  SKIP {path} ({e})"); sys.exit(0)

changed = False
container = data.get(key) if isinstance(data, dict) else None
# JSON shape: { key: { "brainpalace": {...} } }
if isinstance(container, dict) and "brainpalace" in container:
    del container["brainpalace"]; changed = True
# YAML (Continue) shape: { mcpServers: [ {name: brainpalace, ...}, ... ] }
elif isinstance(container, list):
    new = [x for x in container if not (isinstance(x, dict) and x.get("name") == "brainpalace")]
    if len(new) != len(container):
        data[key] = new; changed = True

if not changed:
    print(f"  - {path}: no brainpalace entry"); sys.exit(0)

bak = path.with_suffix(path.suffix + f".bak.{int(time.time())}")
bak.write_text(path.read_text())
if kind == "yaml":
    import yaml
    path.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False))
else:
    path.write_text(json.dumps(data, indent=2) + "\n")
print(f"  REMOVED brainpalace from {path}  (backup: {bak.name})")
PY
        done
        # .kilo/kilo.jsonc — JSON-with-comments, unsafe to auto-edit.
        kilo="$base/.kilo/kilo.jsonc"
        [[ -f "$kilo" ]] && grep -q '"brainpalace"' "$kilo" 2>/dev/null \
            && warn "  $kilo contains a brainpalace entry — edit by hand (jsonc, not auto-parsed)."
    done
    ok "MCP configs processed."
else
    warn "Skipped MCP cleanup."
fi

# -----------------------------------------------------------------------------
# Step 4 — Uninstall the package (auto-detect the manager)
# -----------------------------------------------------------------------------

step "Step 4/7 — Uninstall the package"

UNINSTALLED=0
detect_and_uninstall() {
    # pipx
    if command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q "brainpalace-cli"; then
        say "Detected pipx install."
        confirm "Run: pipx uninstall brainpalace-cli ?" "y" \
            && { pipx uninstall brainpalace-cli >/dev/tty 2>&1 && ok "  pipx package removed."; UNINSTALLED=1; }
    fi
    # uv
    if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q "brainpalace-cli"; then
        say "Detected uv tool install."
        confirm "Run: uv tool uninstall brainpalace-cli ?" "y" \
            && { uv tool uninstall brainpalace-cli >/dev/tty 2>&1 && ok "  uv package removed."; UNINSTALLED=1; }
    fi
    # pip / conda (same command; pip sees both dists)
    if command -v pip >/dev/null 2>&1 && pip show brainpalace-cli >/dev/null 2>&1; then
        local ctx="pip"; [[ -n "${CONDA_DEFAULT_ENV:-}" ]] && ctx="pip (conda env: $CONDA_DEFAULT_ENV)"
        say "Detected $ctx install."
        if confirm "Run: pip uninstall brainpalace-rag brainpalace-cli -y ?" "y"; then
            if pip uninstall brainpalace-rag brainpalace-cli -y >/dev/tty 2>&1; then
                ok "  pip packages removed."; UNINSTALLED=1
            elif pip uninstall brainpalace-rag brainpalace-cli -y --break-system-packages >/dev/tty 2>&1; then
                # PEP 668: Debian/Ubuntu system Python is "externally managed" and
                # refuses a bare uninstall. Retry with the documented override.
                ok "  pip packages removed (--break-system-packages)."; UNINSTALLED=1
            else
                warn "  pip uninstall failed — remove the package manually."
            fi
        fi
    fi
}
detect_and_uninstall
if [[ "$UNINSTALLED" -eq 0 ]]; then
    warn "No managed brainpalace-cli install auto-detected (pipx/uv/pip)."
    warn "If you installed another way, uninstall the package manually."
fi

# -----------------------------------------------------------------------------
# Step 5 — Per-project .brainpalace/ state (multi-select)
# -----------------------------------------------------------------------------

step "Step 5/7 — Delete per-project state  (⚠️ includes archived raw transcripts)"

# Build the candidate list: registry projects whose .brainpalace/ exists, plus
# an optional bounded filesystem scan to catch untracked ones.
declare -a STATE_DIRS=()
for p in "${PROJECTS[@]}"; do
    [[ -d "$p/.brainpalace" ]] && STATE_DIRS+=("$p/.brainpalace")
done
if confirm "Also scan under \$HOME for untracked .brainpalace/ dirs (may be slow)?" "n"; then
    while IFS= read -r d; do
        # de-dupe against what we already have
        skip=0; for e in "${STATE_DIRS[@]}"; do [[ "$e" == "$d" ]] && skip=1; done
        [[ "$skip" -eq 0 ]] && STATE_DIRS+=("$d")
    done < <(find "$HOME" -maxdepth 6 -type d -name ".brainpalace" 2>/dev/null)
fi

if [[ ${#STATE_DIRS[@]} -eq 0 ]]; then
    say "No per-project .brainpalace/ directories found."
else
    echo >/dev/tty
    say "Found ${#STATE_DIRS[@]} project state dir(s):"
    i=1
    for d in "${STATE_DIRS[@]}"; do
        sz="$(du -sh "$d" 2>/dev/null | cut -f1)"
        printf '   %d) %-6s %s\n' "$i" "${sz:-?}" "$d" >/dev/tty
        i=$((i+1))
    done
    echo >/dev/tty
    say "Select which to DELETE: space/comma-separated numbers, ranges (1-3), 'all', or blank to skip."
    printf 'Delete: ' >/dev/tty
    IFS= read -r SEL </dev/tty || SEL=""
    declare -a TO_DELETE=()
    if [[ "${SEL,,}" == "all" ]]; then
        TO_DELETE=("${STATE_DIRS[@]}")
    elif [[ -n "$SEL" ]]; then
        SEL="${SEL//,/ }"
        for tok in $SEL; do
            if [[ "$tok" =~ ^([0-9]+)-([0-9]+)$ ]]; then
                for ((n=${BASH_REMATCH[1]}; n<=${BASH_REMATCH[2]}; n++)); do
                    [[ -n "${STATE_DIRS[$((n-1))]:-}" ]] && TO_DELETE+=("${STATE_DIRS[$((n-1))]}")
                done
            elif [[ "$tok" =~ ^[0-9]+$ ]]; then
                [[ -n "${STATE_DIRS[$((tok-1))]:-}" ]] && TO_DELETE+=("${STATE_DIRS[$((tok-1))]}")
            else
                warn "  ignoring invalid token: $tok"
            fi
        done
    fi
    if [[ ${#TO_DELETE[@]} -eq 0 ]]; then
        warn "Nothing selected — kept all project state."
    else
        echo >/dev/tty
        say "Will delete:"; for d in "${TO_DELETE[@]}"; do printf '     %s\n' "$d" >/dev/tty; done
        if confirm "Confirm IRREVERSIBLE deletion of the above?" "n"; then
            for d in "${TO_DELETE[@]}"; do rm -rf "$d" && ok "  deleted $d"; done
        else
            warn "Aborted deletion — kept all project state."
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Step 6 — Global state (XDG + legacy)
# -----------------------------------------------------------------------------

step "Step 6/7 — Delete global state"

declare -a GLOBAL_DIRS=("$XDG_CFG" "$XDG_STATE" "$XDG_DATA" "$LEGACY_DIR")
FOUND_GLOBAL=0
for d in "${GLOBAL_DIRS[@]}"; do [[ -e "$d" ]] && { FOUND_GLOBAL=1; break; }; done

if [[ "$FOUND_GLOBAL" -eq 0 ]]; then
    say "No global state dirs present."
else
    say "Global state dirs:"
    for d in "${GLOBAL_DIRS[@]}"; do [[ -e "$d" ]] && printf '     %s\n' "$d" >/dev/tty; done
    if confirm "Delete all of the above (config, registry, data, legacy)?" "y"; then
        for d in "${GLOBAL_DIRS[@]}"; do [[ -e "$d" ]] && { rm -rf "$d" && ok "  deleted $d"; }; done
    else
        warn "Kept global state."
    fi
fi

# -----------------------------------------------------------------------------
# Step 7 — Shell rc / API keys  (manual, by design)
# -----------------------------------------------------------------------------

step "Step 7/7 — Shell rc / API keys  (manual)"

cat >/dev/tty <<EOF
We do ${c_bold}not${c_reset} touch your shell rc — an exported API key is often shared
with other tools/projects. Remove these yourself if they were only for
BrainPalace:

  - any  ${c_bold}export <PROVIDER>_API_KEY=...${c_reset}  you added (OPENAI/ANTHROPIC/…)
  - the  ${c_bold}pipx ensurepath${c_reset}  PATH line, ${c_bold}only if${c_reset} brainpalace was your sole pipx tool
EOF

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

cat >/dev/tty <<EOF

${c_gr}Uninstall finished.${c_reset}

Verify:
  command -v brainpalace        # should print nothing
  ls ~/.local/state/brainpalace # should not exist (if you deleted global state)

If anything remains that you wanted gone, re-run this script — every step is
idempotent.
EOF
