#!/bin/bash
# BrainPalace SessionStart hook — THIN SHIM. Do NOT add logic here.
#
# All behavior + injected text live in the CLI (`brainpalace hook sessionstart`),
# so a `pip`/CLI upgrade propagates every change without rewriting this file —
# the shim contains nothing version-specific and cannot go stale. See
# CLAUDE.md → "AI-guidance parity".
#
# Fail-soft: never block a session. CLI absent from PATH — or present but too old
# to have the `hook` command (plugin newer than the installed CLI) — must no-op
# silently, not surface an error a UserPromptSubmit/PreToolUse hook turns into a
# block. So swallow a failing `hook` call (stderr hidden) and exit 0.
command -v brainpalace >/dev/null 2>&1 || exit 0
brainpalace hook sessionstart "$@" 2>/dev/null || exit 0
