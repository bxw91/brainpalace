#!/usr/bin/env bash
# bp-setup-check.sh — BrainPalace pre-flight detection
# Usage: bash /path/to/bp-setup-check.sh
# Output: JSON object with current environment state
#
# When the brainpalace CLI is installed, the canonical source of truth is
# `brainpalace doctor --json`. This script still emits the environment
# snapshot below (Ollama/Docker/large dirs) which the plugin wizard
# consumes, but it also includes a "doctor" key delegating to the CLI's
# checks so the two surfaces never drift out of sync.

# Use set -uo pipefail without -e to avoid aborting on tool-not-found
set -uo pipefail

# --- BrainPalace installation ---
BP_VERSION=$(brainpalace --version 2>/dev/null | head -1 | tr -d '\n' || true)
if [ -n "$BP_VERSION" ]; then
  BP_INSTALLED="true"
else
  BP_INSTALLED="false"
fi

# --- Doctor report (delegates to CLI when available) ---
DOCTOR_JSON="null"
if [ "$BP_INSTALLED" = "true" ]; then
  # brainpalace doctor exits non-zero on critical failures but always emits
  # a JSON body on --json; capture it either way.
  DOCTOR_OUTPUT=$(brainpalace doctor --json 2>/dev/null || true)
  if [ -n "$DOCTOR_OUTPUT" ]; then
    DOCTOR_JSON="$DOCTOR_OUTPUT"
  fi
fi

# --- Config file detection (XDG + legacy) ---
CONFIG_FILE=""
CONFIG_FOUND="false"
for candidate in ".brainpalace/config.yaml" \
    "${XDG_CONFIG_HOME:-$HOME/.config}/brainpalace/config.yaml" \
    "$HOME/.brainpalace/config.yaml"; do
  if [ -f "$candidate" ]; then
    CONFIG_FILE="$candidate"
    CONFIG_FOUND="true"
    break
  fi
done

# --- Ollama detection ---
OLLAMA_RUNNING="false"
OLLAMA_MODELS="[]"

# Method 1: curl root endpoint
if curl -s --connect-timeout 3 http://localhost:11434/ 2>/dev/null | grep -q "Ollama" 2>/dev/null; then
  OLLAMA_RUNNING="true"
fi

# Method 2: lsof port check (if method 1 failed)
if [ "$OLLAMA_RUNNING" = "false" ]; then
  if lsof -i :11434 -sTCP:LISTEN >/dev/null 2>&1; then
    OLLAMA_RUNNING="true"
  fi
fi

# Method 3: ollama list (if method 1+2 failed)
if [ "$OLLAMA_RUNNING" = "false" ]; then
  if ollama list >/dev/null 2>&1; then
    OLLAMA_RUNNING="true"
  fi
fi

# Collect model names if Ollama is running
if [ "$OLLAMA_RUNNING" = "true" ]; then
  # Build JSON array of model names
  MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | \
    python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || true)
  if [ -n "$MODELS" ]; then
    OLLAMA_MODELS="$MODELS"
  fi
fi

# --- Docker detection ---
DOCKER_AVAILABLE="false"
DOCKER_COMPOSE_AVAILABLE="false"
if docker --version >/dev/null 2>&1; then
  DOCKER_AVAILABLE="true"
fi
if docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE_AVAILABLE="true"
fi

# --- Python version ---
PYTHON_VERSION=$(python3 --version 2>/dev/null | cut -d' ' -f2 || true)

# --- API key presence (boolean only — never print key values) ---
if [ -n "${OPENAI_API_KEY:-}" ]; then
  OPENAI_KEY_SET="true"
else
  OPENAI_KEY_SET="false"
fi
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  ANTHROPIC_KEY_SET="true"
else
  ANTHROPIC_KEY_SET="false"
fi
if [ -n "${GOOGLE_API_KEY:-}" ]; then
  GOOGLE_KEY_SET="true"
else
  GOOGLE_KEY_SET="false"
fi

# --- PostgreSQL port scan (5432-5442) ---
AVAILABLE_POSTGRES_PORT=""
for port in $(seq 5432 5442); do
  if ! lsof -i :"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    AVAILABLE_POSTGRES_PORT=$port
    break
  fi
done

# --- Large directory detection ---
# Check for common cache/dependency directories in current working directory
LARGE_DIRS="[]"
LARGE_DIR_LIST=""
for dir in node_modules .venv venv __pycache__ .git dist build target .next .nuxt coverage .pytest_cache .mypy_cache .tox vendor packages Pods .gradle .m2; do
  if [ -d "$dir" ]; then
    SIZE=$(du -sh "$dir" 2>/dev/null | cut -f1 || echo "?")
    # head caps the walk on monster dirs (find dies on SIGPIPE — that's fine).
    COUNT=$(find "$dir" -type f 2>/dev/null | head -20000 | wc -l | tr -d ' ' || echo "0")
    entry="{\"path\":\"$dir\",\"size\":\"$SIZE\",\"file_count\":$COUNT}"
    if [ -z "$LARGE_DIR_LIST" ]; then
      LARGE_DIR_LIST="$entry"
    else
      LARGE_DIR_LIST="$LARGE_DIR_LIST,$entry"
    fi
  fi
done
if [ -n "$LARGE_DIR_LIST" ]; then
  LARGE_DIRS="[$LARGE_DIR_LIST]"
fi

# --- Output JSON ---
# Values are handed to python via env and serialized there, so a quote or
# backslash in any of them can never break the JSON.
export BP_INSTALLED BP_VERSION CONFIG_FOUND CONFIG_FILE OLLAMA_RUNNING \
  OLLAMA_MODELS DOCKER_AVAILABLE DOCKER_COMPOSE_AVAILABLE PYTHON_VERSION \
  OPENAI_KEY_SET ANTHROPIC_KEY_SET GOOGLE_KEY_SET AVAILABLE_POSTGRES_PORT \
  LARGE_DIRS DOCTOR_JSON
python3 - <<'PY'
import json
import os


def _bool(name: str) -> bool:
    return os.environ.get(name) == "true"


def _json_env(name: str, default: str):
    try:
        return json.loads(os.environ.get(name) or default)
    except Exception:
        return json.loads(default)


print(json.dumps({
    "brainpalace_installed": _bool("BP_INSTALLED"),
    "brainpalace_version": os.environ.get("BP_VERSION", ""),
    "config_file_found": _bool("CONFIG_FOUND"),
    "config_file_path": os.environ.get("CONFIG_FILE", ""),
    "ollama_running": _bool("OLLAMA_RUNNING"),
    "ollama_models": _json_env("OLLAMA_MODELS", "[]"),
    "docker_available": _bool("DOCKER_AVAILABLE"),
    "docker_compose_available": _bool("DOCKER_COMPOSE_AVAILABLE"),
    "python_version": os.environ.get("PYTHON_VERSION", ""),
    "api_keys": {
        "openai": _bool("OPENAI_KEY_SET"),
        "anthropic": _bool("ANTHROPIC_KEY_SET"),
        "google": _bool("GOOGLE_KEY_SET"),
    },
    "available_postgres_port": os.environ.get("AVAILABLE_POSTGRES_PORT", ""),
    "large_dirs": _json_env("LARGE_DIRS", "[]"),
    "doctor": _json_env("DOCTOR_JSON", "null"),
}, indent=2))
PY
