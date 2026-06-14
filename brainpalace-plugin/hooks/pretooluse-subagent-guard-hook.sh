#!/bin/bash
# BrainPalace PreToolUse subagent guard — THIN SHIM. Do NOT add logic here.
#
# All behavior + text live in the CLI (`brainpalace hook pretooluse`), so a
# `pip`/CLI upgrade propagates every change without rewriting this file — the
# shim contains nothing version-specific and cannot go stale. See
# CLAUDE.md → "AI-guidance parity" and posttooluse-docsync-hook.sh for the pattern.
#
# Gates Agent/Task spawns: when enabled via `cli.subagent_guard.enabled`, a spawn
# whose prompt lacks a `brainpalace query --mode` directive is denied (enforce)
# or nudged (advisory). Disabled by default — no-op unless the user opts in.
#
# Fail-soft: if the CLI is not on PATH, no-op silently (never block a spawn).
command -v brainpalace >/dev/null 2>&1 || exit 0
exec brainpalace hook pretooluse "$@"
