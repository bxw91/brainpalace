#!/bin/bash
# BrainPalace PostToolUse doc-sync nudge — THIN SHIM. Do NOT add logic here.
#
# All behavior + injected text live in the CLI (`brainpalace hook posttooluse`),
# so a `pip`/CLI upgrade propagates every change without rewriting this file —
# the shim contains nothing version-specific and cannot go stale. See
# CLAUDE.md → "AI-guidance parity" and the sessionstart-hook for the pattern.
#
# Fail-soft: if the CLI is not on PATH, no-op silently (never block a session).
command -v brainpalace >/dev/null 2>&1 || exit 0
# Present-but-too-old CLI (no `hook` command) must no-op silently, exactly like
# the plugin shims — never surface an error into the session.
brainpalace hook posttooluse "$@" 2>/dev/null || exit 0
