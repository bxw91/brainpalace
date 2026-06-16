#!/usr/bin/env bash
#
# dev-install-from-source.sh — reinstall BrainPalace (CLI + server + dashboard)
# from THIS local source tree over the existing pipx install, then restore the
# exact set of project servers + dashboard that were running before.
#
# Repo-development tooling. Fully automatic and idempotent:
#   1. snapshot which project servers + the dashboard are currently running
#   2. stop them all (force) and VERIFY everything is down before touching files
#   3. pipx install --force the local CLI, then inject the local server + dashboard
#      (the published brainpalace-rag / brainpalace-dashboard deps are overridden)
#   4. restart exactly what was running before — servers first, then the dashboard
#      if (and only if) it was up before
#
# It deliberately refuses to reinstall while anything is still running, so you
# never replace the package under a live old process.
#
# Usage:
#   scripts/dev-install-from-source.sh            # full auto (stop → install → restore)
#   scripts/dev-install-from-source.sh --no-restart   # stop + install, leave stopped
#   scripts/dev-install-from-source.sh --dry-run      # print the plan, change nothing
#
# Via Taskfile:
#   task install:from-source
#   task install:from-source -- --dry-run
set -euo pipefail

# Headless-safe: avoid the DBus/SecretService keyring prompt during pipx installs.
export PYTHON_KEYRING_BACKEND="${PYTHON_KEYRING_BACKEND:-keyring.backends.null.Keyring}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_DIR="$REPO_ROOT/brainpalace-cli"
SERVER_DIR="$REPO_ROOT/brainpalace-server"
DASH_DIR="$REPO_ROOT/brainpalace-dashboard"

NO_RESTART=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --no-restart) NO_RESTART=1 ;;
    --dry-run)    DRY_RUN=1 ;;
    -h|--help)    sed -n '2,30p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;36m[install-from-source]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[install-from-source] ERROR:\033[0m %s\n' "$*" >&2; }
run() { if [ "$DRY_RUN" -eq 1 ]; then printf '  + %s\n' "$*"; else "$@"; fi; }

for bin in pipx jq brainpalace; do
  command -v "$bin" >/dev/null || { err "'$bin' not found on PATH"; exit 1; }
done
for d in "$CLI_DIR" "$SERVER_DIR" "$DASH_DIR"; do
  [ -d "$d" ] || { err "package dir missing: $d (run from a source checkout)"; exit 1; }
done

# --- 1. snapshot running state (with the OLD cli, before we replace it) --------
log "Snapshotting running instances…"
mapfile -t RUNNING_ROOTS < <(brainpalace list --json 2>/dev/null \
  | jq -r '.instances[] | select(.status=="running") | .project_root' || true)
# Drop any empty entries so counts/iteration are clean under `set -u`.
TMP=(); for r in "${RUNNING_ROOTS[@]:-}"; do [ -n "$r" ] && TMP+=("$r"); done
RUNNING_ROOTS=("${TMP[@]:-}")
N_SERVERS=0; for r in "${RUNNING_ROOTS[@]:-}"; do [ -n "$r" ] && N_SERVERS=$((N_SERVERS+1)); done

DASH_WAS_RUNNING=0
if [ "$(brainpalace dashboard status --json 2>/dev/null | jq -r '.status // "stopped"')" = "running" ]; then
  DASH_WAS_RUNNING=1
fi
log "Running servers: $N_SERVERS | dashboard: $([ "$DASH_WAS_RUNNING" -eq 1 ] && echo running || echo stopped)"
for r in "${RUNNING_ROOTS[@]:-}"; do [ -n "$r" ] && log "  - $r"; done

# --- 2. stop everything --------------------------------------------------------
log "Stopping all servers + dashboard…"
for r in "${RUNNING_ROOTS[@]:-}"; do
  [ -n "$r" ] || continue
  run brainpalace stop --path "$r" --force --timeout 15 || err "stop failed for $r (continuing)"
done
run brainpalace dashboard stop || true
run brainpalace stop --all --force || true   # reap any orphan server processes

# --- 3. verify down before reinstalling ---------------------------------------
if [ "$DRY_RUN" -eq 0 ]; then
  log "Verifying shutdown…"
  deadline=$(( SECONDS + 45 ))
  while :; do
    total="$(brainpalace list --json 2>/dev/null | jq -r '.total // 0')"
    dash="$(brainpalace dashboard status --json 2>/dev/null | jq -r '.status // "stopped"')"
    if [ "$total" = "0" ] && [ "$dash" != "running" ]; then
      log "Confirmed: 0 servers running, dashboard stopped."
      break
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      err "Timed out waiting for shutdown (servers=$total, dashboard=$dash). Aborting BEFORE reinstall."
      exit 1
    fi
    sleep 1
  done
fi

# --- 4. install from source ----------------------------------------------------
log "Installing local CLI (pipx install --force)…"
run pipx install --force "$CLI_DIR"
log "Injecting local server + dashboard (pipx inject --force)…"
run pipx inject --force brainpalace-cli "$SERVER_DIR" "$DASH_DIR"
[ "$DRY_RUN" -eq 0 ] && log "Now installed: $(brainpalace --version 2>/dev/null || echo '?')"

# --- 5. restart exactly what was running --------------------------------------
if [ "$NO_RESTART" -eq 1 ]; then
  log "--no-restart: leaving everything stopped. Done."
  exit 0
fi

log "Restarting the $N_SERVERS server(s) that were running…"
for r in "${RUNNING_ROOTS[@]:-}"; do
  [ -n "$r" ] || continue
  # --no-dashboard: control the dashboard explicitly below (and avoid a browser pop).
  run brainpalace start --path "$r" --no-dashboard --timeout 120 || err "restart failed for $r"
done
if [ "$DASH_WAS_RUNNING" -eq 1 ]; then
  log "Restarting dashboard (was running before)…"
  run brainpalace dashboard start --no-open || err "dashboard restart failed"
else
  log "Dashboard was stopped before — leaving it stopped."
fi

# --- verify back up ------------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ]; then
  deadline=$(( SECONDS + 120 ))
  while :; do
    total="$(brainpalace list --json 2>/dev/null | jq -r '.total // 0')"
    [ "$total" -ge "$N_SERVERS" ] && break
    if [ "$SECONDS" -ge "$deadline" ]; then
      err "Only $total/$N_SERVERS server(s) came back up within timeout."
      break
    fi
    sleep 2
  done
  log "Restore complete: ${total:-0}/$N_SERVERS server(s) up$([ "$DASH_WAS_RUNNING" -eq 1 ] && echo ' + dashboard')."
fi
