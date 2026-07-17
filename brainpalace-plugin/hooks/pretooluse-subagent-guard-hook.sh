#!/bin/bash
# BrainPalace PreToolUse subagent guard — THIN SHIM. Do NOT add logic here.
#
# All behavior + text live in the CLI (`brainpalace hook pretooluse`), so a
# `pip`/CLI upgrade propagates every change without rewriting this file — the
# shim contains nothing version-specific and cannot go stale. See
# CLAUDE.md → "AI-guidance parity" and sessionstart-hook.sh for the pattern.
#
# Two sibling guards dispatched by tool name (matcher Agent|Task|Grep|Glob):
#   - subagent guard (Agent/Task): a spawn whose prompt lacks a `brainpalace
#     query --mode` directive (or the MCP query-tool `mode:` arg) is nudged
#     (advisory) or denied (enforce). Knobs: `cli.subagent_guard.*` /
#     `BRAINPALACE_SUBAGENT_GUARD`.
#   - search guard (Grep/Glob): the main thread's own Grep/Glob is steered to
#     `brainpalace query` the same way. Knobs: `cli.search_guard.*` /
#     `BRAINPALACE_SEARCH_GUARD`. (Bash is not matched — escape hatch for raw
#     search of non-indexed files.)
# Both ON by default, but with different default modes, and ONLY while this
# project's BrainPalace server is running (no live server → no-op). The
# subagent guard defaults to `enforce` (a search-shaped spawn missing a
# `--mode` directive is denied — safe by default because it only fires on
# spawns an intent gate already flags as codebase search/exploration); the
# search guard defaults to `advisory` (a nudge, never a deny — it fires on
# every Grep/Glob including other plugins', so denying by default would be
# too blunt). Soften the subagent guard to `advisory`, or opt the search
# guard into `enforce`, with the relevant `*.mode:`; disable either with
# `*.enabled: false` / `=off`.
#
# Fail-soft: never block a spawn. CLI absent from PATH — or present but too old to
# have the `hook` command (plugin newer than the installed CLI) — must no-op
# silently, not surface an error this PreToolUse hook turns into a block. So
# swallow a failing `hook` call (stderr hidden) and exit 0.
command -v brainpalace >/dev/null 2>&1 || exit 0
brainpalace hook pretooluse "$@" 2>/dev/null || exit 0
