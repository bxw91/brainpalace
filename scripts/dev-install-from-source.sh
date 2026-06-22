#!/usr/bin/env bash
#
# dev-install-from-source.sh — reinstall BrainPalace (CLI + server + dashboard)
# from THIS local source tree over the existing pipx install, then restore the
# exact set of project servers + dashboard that were running before.
#
# Repo-development tooling. Fully automatic and idempotent:
#   1. rebuild the dashboard SPA from the CURRENT frontend source (npm ci + build)
#      so the injected dashboard never ships a stale static/ bundle (static/ is
#      gitignored generated output, not committed)
#   2. snapshot which project servers + the dashboard are currently running
#   3. stop them all (force) and VERIFY everything is down before touching files
#   4. pipx install --force the local CLI, then inject the local server + dashboard
#      (the published brainpalace-rag / brainpalace-dashboard deps are overridden),
#      then re-pin the local CLI last (--no-deps) so the inject can't downgrade it
#   5. restart exactly what was running before — servers first, then the dashboard
#      if (and only if) it was up before
#
# Guarantee: everything installed is built from THIS source tree — the SPA from
# frontend/src (rebuilt here), the Python packages with --no-cache-dir fresh wheels.
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

for bin in pipx jq brainpalace curl npm node; do
  command -v "$bin" >/dev/null || { err "'$bin' not found on PATH"; exit 1; }
done
for d in "$CLI_DIR" "$SERVER_DIR" "$DASH_DIR"; do
  [ -d "$d" ] || { err "package dir missing: $d (run from a source checkout)"; exit 1; }
done

# --- source provenance: prove WHAT tree we are about to install ----------------
# This script installs the working tree as-is (incl. uncommitted edits) — that is
# the point of a from-source install. Log the exact branch + commit + dirty state
# so it is unambiguous which source the local install now reflects.
if command -v git >/dev/null && git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  GIT_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  GIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"
  GIT_DIRTY=""; git -C "$REPO_ROOT" diff --quiet 2>/dev/null && git -C "$REPO_ROOT" diff --cached --quiet 2>/dev/null || GIT_DIRTY=" +local-uncommitted-changes"
  log "Source tree: $REPO_ROOT @ ${GIT_BRANCH}/${GIT_SHA}${GIT_DIRTY}"
else
  log "Source tree: $REPO_ROOT (not a git checkout)"
fi

# --- 0. rebuild the dashboard SPA from CURRENT source -------------------------
# pip/pipx packages whatever already sits in brainpalace_dashboard/static/. That
# compiled bundle is gitignored generated output (NOT committed), so a fresh
# checkout may have no SPA at all, or a stale one from an earlier build. Rebuild
# it here so the injected dashboard always reflects this tree's frontend/src.
# Done BEFORE stopping any servers: a build failure aborts (set -e) without having
# torn down running instances. `npm ci` (not install) + vite's emptyOutDir wipe and
# regenerate static/ from the lockfile — reproducible, no leftovers from old builds.
FRONTEND_DIR="$DASH_DIR/frontend"
STATIC_DIR="$DASH_DIR/brainpalace_dashboard/static"
log "Rebuilding dashboard SPA from current source ($FRONTEND_DIR)…"
if [ "$DRY_RUN" -eq 1 ]; then
  printf '  + (cd %s && rm -rf static node_modules/.vite *.tsbuildinfo && npm ci && npm run build)\n' "$FRONTEND_DIR"
else
  # Purge every build cache first so `tsc -b` / vite cannot reuse a stale
  # incremental artifact — the compile must come only from current frontend/src:
  #   - the old static/ output     (vite's emptyOutDir also wipes it, belt+braces)
  #   - tsc's *.tsbuildinfo         (incremental typecheck cache)
  #   - node_modules/.vite          (vite's transform/dep cache)
  rm -rf "$STATIC_DIR" "$FRONTEND_DIR"/node_modules/.vite "$FRONTEND_DIR"/*.tsbuildinfo
  # `npm ci` installs registry deps strictly from package-lock.json into a clean
  # node_modules (it deletes any existing one) — reproducible, lockfile-pinned.
  ( cd "$FRONTEND_DIR" && npm ci && npm run build )
  # Freshness guard: the build must have produced static/ assets newer than every
  # frontend/src file. If not, the build silently no-op'd (or wrote elsewhere) and
  # we'd ship a stale UI — fail loud now instead of injecting the old bundle.
  newest_src="$(find "$FRONTEND_DIR/src" -type f -printf '%T@\n' 2>/dev/null | sort -nr | head -1)"
  newest_out="$(find "$STATIC_DIR" -type f -printf '%T@\n' 2>/dev/null | sort -nr | head -1)"
  if [ -z "$newest_out" ] || awk "BEGIN{exit !(${newest_src:-0} > ${newest_out:-0})}"; then
    err "dashboard SPA build did not refresh $STATIC_DIR (built assets older than frontend/src). Aborting BEFORE install so no stale UI is shipped."
    exit 1
  fi
  log "Dashboard SPA rebuilt: $STATIC_DIR is current with frontend/src."
fi

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
# Run pipx from a neutral dir: if cwd contains a 'brainpalace-cli' folder (e.g.
# the repo root), pipx misreads the venv-name arg as a path and aborts.
cd /
# --no-cache-dir on every local-source install: pip's wheel cache keys a build on
# the SOURCE PATH (the `file://` link), not the version, so all builds of a package
# land in one cache bucket. inject would then re-serve a STALE wheel (e.g. an old
# 26.6.37 cli/server/dashboard built days ago) for the unchanged path instead of
# rebuilding the current tree — silently injecting an old server/dashboard. Forcing
# a fresh build kills that for all three packages (the CLI pin below only covered
# the cli). PyPI deps (fastapi, …) are unaffected; only the local builds skip cache.
log "Installing local CLI (pipx install --force, fresh build)…"
run pipx install --force --pip-args=--no-cache-dir "$CLI_DIR"
log "Injecting local server + dashboard (pipx inject --force, fresh build)…"
run pipx inject --force --pip-args=--no-cache-dir brainpalace-cli "$SERVER_DIR" "$DASH_DIR"
# Reinstall the local CLI LAST, with --no-deps. The inject above re-resolves
# brainpalace-cli as a dependency of the server/dashboard; when the local version
# is UNRELEASED, pip downgrades it to the latest PUBLISHED CLI — silently dropping
# new subcommands like `hook`, which breaks every Claude Code hook shim. Pinning
# the local CLI back here (deps untouched, so the injected server/dashboard stay)
# guarantees the venv ends on the local build regardless of what inject resolved.
log "Pinning local CLI last (pipx runpip --no-deps) so the inject can't downgrade it…"
run pipx runpip brainpalace-cli install --no-deps --force-reinstall "$CLI_DIR"
[ "$DRY_RUN" -eq 0 ] && log "Now installed: $(brainpalace --version 2>/dev/null || echo '?')"

# --- 4b. verify the INSTALLED dashboard serves the freshly built SPA ----------
# Strongest "did it really update from source" check: the dashboard wheel pipx
# just injected must contain the static/ bundle we rebuilt above — not a stale
# cached wheel. index.html references the content-hashed asset filenames, so an
# identical index.html proves an identical bundle. Compare byte-for-byte.
if [ "$DRY_RUN" -eq 0 ]; then
  DASH_LOC="$(pipx runpip brainpalace-cli show brainpalace-dashboard 2>/dev/null | awk -F': ' '/^Location:/{print $2}')"
  installed_html="${DASH_LOC%/}/brainpalace_dashboard/static/index.html"
  source_html="$STATIC_DIR/index.html"
  if [ -z "$DASH_LOC" ] || [ ! -f "$installed_html" ]; then
    err "could not locate the installed dashboard static bundle (Location='$DASH_LOC') — cannot confirm the SPA updated from source. Aborting."
    exit 1
  fi
  if ! cmp -s "$installed_html" "$source_html"; then
    err "INSTALLED dashboard SPA differs from the source build — pipx injected a stale/cached wheel. Try 'pipx uninstall brainpalace-cli' then re-run."
    exit 1
  fi
  log "Verified: installed dashboard serves the SPA just built from current source."
fi

# --- 5. restart exactly what was running --------------------------------------
if [ "$NO_RESTART" -eq 1 ]; then
  log "--no-restart: leaving everything stopped. Done."
  exit 0
fi

log "Restarting the $N_SERVERS server(s) that were running…"
for r in "${RUNNING_ROOTS[@]:-}"; do
  [ -n "$r" ] || continue
  # A session-autostart hook can re-spawn a STALE-version server during the
  # (slow) pipx build window above. `brainpalace start` would then no-op with
  # "already running" and we'd silently adopt the old build. Force it down
  # first so the relaunch is guaranteed to be the just-installed version.
  run brainpalace stop --path "$r" --force --timeout 15 || true
  # --no-dashboard: control the dashboard explicitly below (and avoid a browser pop).
  run brainpalace start --path "$r" --no-dashboard --timeout 120 || err "restart failed for $r"
done
if [ "$DASH_WAS_RUNNING" -eq 1 ]; then
  log "Restarting dashboard (was running before)…"
  run brainpalace dashboard stop || true   # drop any raced-in stale dashboard
  run brainpalace dashboard start --no-open || err "dashboard restart failed"
else
  log "Dashboard was stopped before — leaving it stopped."
fi

# --- verify back up (count AND version) ---------------------------------------
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
  # A correct count is not enough: a stale-version process that raced in during
  # the install window also satisfies it. Assert each running server reports the
  # version we just installed (/health, suffix-tolerant), so an adopted old build
  # fails loudly instead of masquerading as a successful reinstall.
  # `|| true` on both probes: these are bare `var=$(pipeline)` assignments, and
  # under `set -euo pipefail` a no-match `grep` (e.g. a /health that omits a
  # version) makes the pipeline non-zero, which aborts the whole script on the
  # assignment line — reporting a bogus `exit 1` even though the install fully
  # succeeded. The `[ -n "$got" ]` guard below already treats empty as "skip", so
  # swallow the pipeline status and let the check degrade gracefully instead.
  want="$(brainpalace --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  stale=0
  while IFS= read -r url; do
    [ -n "$url" ] || continue
    got="$(curl -fsS "$url/health" 2>/dev/null | jq -r '.version // empty' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
    if [ -n "$want" ] && [ -n "$got" ] && [ "$got" != "$want" ]; then
      err "server at $url runs $got, expected $want — a stale process was adopted; run 'brainpalace stop --path <root>' then 'brainpalace start'."
      stale=1
    fi
  done < <(brainpalace list --json 2>/dev/null | jq -r '.instances[]? | select(.status=="running") | .base_url')
  log "Restore complete: ${total:-0}/$N_SERVERS server(s) up$([ "$DASH_WAS_RUNNING" -eq 1 ] && echo ' + dashboard')$([ "$stale" -eq 1 ] && echo ' — VERSION MISMATCH (see error above)')."
  [ "$stale" -eq 1 ] && exit 1 || true
fi
