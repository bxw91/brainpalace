#!/bin/bash
# BrainPalace SessionStart hook — THIN SHIM. Do NOT add logic here.
#
# All behavior + injected text live in the CLI (`brainpalace hook sessionstart`),
# so a `pip`/CLI upgrade propagates every change without rewriting this file —
# the shim contains nothing version-specific and cannot go stale. See
# CLAUDE.md → "AI-guidance parity".
#
# Fail-soft: if the CLI is not on PATH, no-op silently (never block a session).
command -v brainpalace >/dev/null 2>&1 || exit 0
exec brainpalace hook sessionstart "$@"
