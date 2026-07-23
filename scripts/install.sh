#!/usr/bin/env bash
# BrainPalace one-line installer.
#
# Installs the `brainpalace` CLI into a dedicated pipx venv. The CLI depends on
# the `brainpalace-rag` server package, so pipx pulls it into the same venv —
# one command gets you both the CLI and the server it launches.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/install.sh | bash
#
# Pin to a version:
#   curl -sSL .../install.sh | bash -s -- --version 26.5.1
#
# Show what would happen, do nothing:
#   curl -sSL .../install.sh | bash -s -- --dry-run
#
# Install from a local checkout instead of PyPI (dev):
#   bash scripts/install.sh --local /path/to/brainpalace
#   Builds CLI + server + dashboard from that tree: it rebuilds the dashboard SPA
#   from frontend/src (needs Node's npm + node) and injects the local server and
#   dashboard, so no push to GitHub/PyPI is needed to test your changes.
#
# Exit codes:
#   0  success
#   1  pre-flight failure (missing pipx / python)
#   2  install step failed
set -euo pipefail

VERSION=""
DRY_RUN=0
LOCAL_PATH=""

usage() {
    sed -n '2,21p' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)
            VERSION="$2"; shift 2 ;;
        --dry-run)
            DRY_RUN=1; shift ;;
        --local)
            LOCAL_PATH="$2"; shift 2 ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
run() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '   [dry-run] %s\n' "$*"
    else
        printf '   %s\n' "$*"
        eval "$@"
    fi
}

# -----------------------------------------------------------------------------
# Pre-flight
# -----------------------------------------------------------------------------

say "Pre-flight checks"

for cmd in python3 pipx; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "   ERROR: required command '$cmd' not found in PATH." >&2
        if [[ "$cmd" == "pipx" ]]; then
            echo "   Install via your package manager (e.g. 'apt install pipx' or" >&2
            echo "   'brew install pipx'), then re-run this installer." >&2
        fi
        exit 1
    fi
done

PIPX_PYTHON_VERSION="$(python3 -c 'import sys; print(".".join(str(x) for x in sys.version_info[:2]))')"
say "Using python3 ${PIPX_PYTHON_VERSION}"

# -----------------------------------------------------------------------------
# Resolve install spec
# -----------------------------------------------------------------------------

PIPX_PIP_ARGS=""
if [[ -n "$LOCAL_PATH" ]]; then
    # Resolve to an absolute path so pipx specs work regardless of CWD (we run
    # pipx from a neutral dir below to dodge name/dir collisions).
    LOCAL_PATH="$(cd "$LOCAL_PATH" && pwd)"
    CLI_SPEC="${LOCAL_PATH}/brainpalace-cli"
    SERVER_SPEC="${LOCAL_PATH}/brainpalace-server"
    DASH_SPEC="${LOCAL_PATH}/brainpalace-dashboard"
    for d in "$CLI_SPEC" "$SERVER_SPEC" "$DASH_SPEC"; do
        [[ -d "$d" ]] || { echo "   ERROR: not a brainpalace checkout — missing $d" >&2; exit 1; }
    done
    # Local builds must skip pip's wheel cache: it keys the cached wheel on the
    # source PATH, not the version, so a repeat install of an edited tree would
    # re-serve a STALE wheel instead of rebuilding. Applies to CLI + both injects.
    PIPX_PIP_ARGS="--pip-args=--no-cache-dir"
    # A local install rebuilds the dashboard SPA from frontend/src (the PyPI path
    # ships a prebuilt static/ bundle; a checkout may have none or a stale one),
    # so it needs the Node toolchain. Fail loud now, before the venv is touched.
    for cmd in npm node; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            echo "   ERROR: --local needs '$cmd' to build the dashboard SPA from source." >&2
            echo "   Install Node.js (provides npm + node), then re-run." >&2
            exit 1
        fi
    done
    say "Installing from local checkout: ${LOCAL_PATH}"
else
    # Bypass pip's HTTP cache so a just-published release isn't masked by a
    # stale simple-index page — that cache is what makes `pipx install` resolve
    # the *previous* version in the minutes after a release.
    if [[ -n "$VERSION" ]]; then
        CLI_SPEC="brainpalace-cli==${VERSION}"
        # Pin the sibling packages to the SAME version so pip installs all three
        # exact and the resolver never explores (or re-downloads) other
        # candidates. brainpalace-dashboard pins brainpalace-cli with an exact
        # '==', so leaving the siblings unpinned makes pip fetch+reject older
        # candidates — minutes of churn on every install/update. brainpalace-rag
        # is always a CLI dependency; brainpalace-dashboard is one only on
        # Python >=3.12 (its Requires-Python), so pin it only there — otherwise
        # the explicit spec breaks the install on 3.10/3.11.
        EXTRA_PINS="brainpalace-rag==${VERSION}"
        if python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)'; then
            EXTRA_PINS="${EXTRA_PINS} brainpalace-dashboard==${VERSION}"
        fi
        PIPX_PIP_ARGS="--pip-args=\"--no-cache-dir ${EXTRA_PINS}\""
    else
        CLI_SPEC="brainpalace-cli"
        # No target version to pin the siblings to; pip resolves latest of each.
        PIPX_PIP_ARGS="--pip-args=--no-cache-dir"
    fi
    say "Installing ${CLI_SPEC} from PyPI"
fi

# -----------------------------------------------------------------------------
# Build the dashboard SPA (local install only)
#
# The dashboard wheel packages whatever sits in brainpalace_dashboard/static/. A
# checkout may have no SPA, or a stale one — so rebuild it from frontend/src here,
# BEFORE any pipx step, so a build failure aborts without a half-swapped venv.
# `npm ci` + vite's emptyOutDir wipe and regenerate static/ from the lockfile.
# -----------------------------------------------------------------------------

if [[ -n "$LOCAL_PATH" ]]; then
    FRONTEND_DIR="${DASH_SPEC}/frontend"
    STATIC_DIR="${DASH_SPEC}/brainpalace_dashboard/static"
    say "Rebuilding dashboard SPA from local source (${FRONTEND_DIR})"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '   [dry-run] (cd %s && rm -rf static node_modules/.vite *.tsbuildinfo && npm ci && npm run build)\n' "$FRONTEND_DIR"
    else
        # Purge stale caches first so tsc -b / vite cannot reuse an incremental
        # artifact — the compile must come only from the current frontend/src.
        rm -rf "$STATIC_DIR" "$FRONTEND_DIR"/node_modules/.vite "$FRONTEND_DIR"/*.tsbuildinfo
        ( cd "$FRONTEND_DIR" && npm ci && npm run build )
        # We wiped static/ above; if the build no-op'd (or wrote elsewhere),
        # index.html is absent — fail before injecting a missing/stale UI.
        [[ -f "${STATIC_DIR}/index.html" ]] || {
            echo "   ERROR: dashboard SPA build did not produce ${STATIC_DIR}/index.html. Aborting before install." >&2
            exit 2
        }
    fi
fi

# -----------------------------------------------------------------------------
# Install
# -----------------------------------------------------------------------------

say "Installing brainpalace-cli via pipx (force-replacing any existing copy)"
run "pipx install --force ${PIPX_PIP_ARGS} '${CLI_SPEC}'"

if [[ -n "$LOCAL_PATH" ]]; then
    # `pipx install` above pulled the PyPI server + dashboard into the venv as CLI
    # deps. Override BOTH with the local checkout so the install reflects source:
    #   --force          replace the already-present PyPI copies (else pipx skips)
    #   --no-cache-dir   force a fresh build (pip's wheel cache is keyed on the
    #                    source PATH, so it would re-serve a stale wheel otherwise)
    #   (cd / && ...)    run from a neutral CWD so the literal name "brainpalace-cli"
    #                    isn't mistaken for the ./brainpalace-cli dir under the repo
    say "Injecting local brainpalace-server + brainpalace-dashboard into the CLI venv"
    run "(cd / && pipx inject --force --pip-args=--no-cache-dir brainpalace-cli '${SERVER_SPEC}' '${DASH_SPEC}')"
    # The inject re-resolves brainpalace-cli as a dep of the server/dashboard; if
    # that pulls the PyPI CLI it would shadow the local one. Re-pin the LOCAL CLI
    # LAST with --no-deps (leaves the injected server/dashboard untouched) so the
    # venv always ends on the local build regardless of what inject resolved.
    say "Pinning local brainpalace-cli last so the inject can't downgrade it"
    run "(cd / && pipx runpip brainpalace-cli install --no-deps --force-reinstall --no-cache-dir '${CLI_SPEC}')"
fi

# -----------------------------------------------------------------------------
# Verify
# -----------------------------------------------------------------------------

say "Verifying installation"
if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "   [dry-run] brainpalace --version"
else
    if command -v brainpalace >/dev/null 2>&1; then
        brainpalace --version
    else
        echo "   WARNING: 'brainpalace' not found in PATH." >&2
        echo "   pipx typically installs to ~/.local/bin — ensure it's on PATH." >&2
        exit 2
    fi
fi

# -----------------------------------------------------------------------------
# Next steps
#
# Suppressed when invoked from guided setup (setup.sh) — that flow prints its
# own, simpler end-of-run guidance, so a mid-flow "Next steps" block here is
# noise. Standalone `install.sh` runs still show it.
# -----------------------------------------------------------------------------

if [[ -z "${BRAINPALACE_GUIDED_SETUP:-}" ]]; then
    cat <<'EOF'

Next steps
----------
* In a project:   cd <project> && brainpalace init

See docs/QUICK_START.md for a first-run walkthrough.
EOF
fi
