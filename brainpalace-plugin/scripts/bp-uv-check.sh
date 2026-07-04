#!/usr/bin/env bash
# bp-uv-check.sh - Report uv availability and install hint when missing.

set -euo pipefail

if uv --version >/dev/null 2>&1; then
  echo "available"
  exit 0
fi

echo "missing"
echo "Install hint: see https://docs.astral.sh/uv/getting-started/installation/ (or: pipx install uv / pip install uv)"
