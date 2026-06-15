#!/usr/bin/env bash
# bp-pypi-version.sh - Resolve latest brainpalace-rag version from PyPI.

set -euo pipefail

PYPI_URL="https://pypi.org/pypi/brainpalace-rag/json"

JSON_PAYLOAD=$(curl -fsS "$PYPI_URL") || {
  echo "Failed to fetch package metadata from PyPI: $PYPI_URL" >&2
  exit 1
}

VERSION=$(printf "%s" "$JSON_PAYLOAD" | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])") || {
  echo "Failed to parse latest version from PyPI response" >&2
  exit 1
}

if [ -z "$VERSION" ]; then
  echo "PyPI response did not contain an brainpalace-rag version" >&2
  exit 1
fi

printf "%s\n" "$VERSION"
