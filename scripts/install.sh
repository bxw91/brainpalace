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

if [[ -n "$LOCAL_PATH" ]]; then
    CLI_SPEC="${LOCAL_PATH}/brainpalace-cli"
    SERVER_SPEC="${LOCAL_PATH}/brainpalace-server"
    say "Installing from local checkout: ${LOCAL_PATH}"
else
    if [[ -n "$VERSION" ]]; then
        CLI_SPEC="brainpalace-cli==${VERSION}"
    else
        CLI_SPEC="brainpalace-cli"
    fi
    say "Installing ${CLI_SPEC} from PyPI"
fi

# -----------------------------------------------------------------------------
# Install
# -----------------------------------------------------------------------------

say "Installing brainpalace-cli via pipx (force-replacing any existing copy)"
run "pipx install --force '${CLI_SPEC}'"

if [[ -n "$LOCAL_PATH" ]]; then
    # From a local checkout the CLI declares brainpalace-rag as a path dependency
    # which pipx cannot resolve in isolation — inject the local server explicitly.
    say "Injecting local brainpalace-server into the CLI venv"
    run "pipx inject brainpalace-cli '${SERVER_SPEC}'"
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
