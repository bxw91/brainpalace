#!/bin/bash
# BrainPalace PreToolUse subagent guard — THIN SHIM. Do NOT add logic here.
#
# All behavior + text live in the CLI (`brainpalace hook pretooluse`), so a
# `pip`/CLI upgrade propagates every change without rewriting this file — the
# shim contains nothing version-specific and cannot go stale. See
# CLAUDE.md → "AI-guidance parity" and posttooluse-docsync-hook.sh for the pattern.
#
# Gates Agent/Task spawns: a spawn whose prompt lacks a `brainpalace query --mode`
# directive (or the equivalent MCP query-tool `mode:` argument) is nudged
# (advisory) or denied (enforce). ON by default in `advisory` mode, but ONLY
# while this project's BrainPalace server is running (no live server → no-op).
# Opt into hard blocking with `cli.subagent_guard.mode: enforce` (or
# `BRAINPALACE_SUBAGENT_GUARD=enforce`); disable entirely with
# `cli.subagent_guard.enabled: false` / `BRAINPALACE_SUBAGENT_GUARD=off`.
#
# Fail-soft: if the CLI is not on PATH, no-op silently (never block a spawn).
command -v brainpalace >/dev/null 2>&1 || exit 0
exec brainpalace hook pretooluse "$@"
