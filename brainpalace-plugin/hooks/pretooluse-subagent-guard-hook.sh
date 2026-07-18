#!/bin/bash
# BrainPalace PreToolUse guard — THIN SHIM. Do NOT add logic here.
#
# All behavior + text live in the CLI (`brainpalace hook pretooluse`), so a
# `pip`/CLI upgrade propagates every change without rewriting this file — the
# shim contains nothing version-specific and cannot go stale. See
# CLAUDE.md → "AI-guidance parity" and sessionstart-hook.sh for the pattern.
#
# Three sibling guards dispatched by tool name (matcher Agent|Task|Grep|Bash):
#   - subagent guard (Agent/Task): a spawn whose prompt lacks a `brainpalace
#     query --mode` directive (or the MCP query-tool `mode:` arg) is denied
#     (enforce, default) or nudged (advisory). Knobs: `cli.subagent_guard.*` /
#     `BRAINPALACE_SUBAGENT_GUARD`.
#   - search guard (Grep): scope-aware — the CLI reacts only when the target
#     is manifest-indexed AND the pattern is one BM25 can answer (regex
#     constructs pass to native Grep). Glob is not matched at all (filename
#     matching has no BM25 mapping). Knobs: `cli.search_guard.*` /
#     `BRAINPALACE_SEARCH_GUARD`. Enforce (deny) by default; advisory softens.
#   - bash search guard (Bash): scope-aware — the CLI reacts only to a
#     recursive/`rg` search whose target the folder manifests mark as indexed;
#     non-search Bash, non-indexed targets (the raw-search escape hatch, now
#     scoped), and regex constructs BM25 cannot honor pass untouched. Same
#     `cli.search_guard.*` knobs.
# All ON by default, but ONLY while this project's BrainPalace server is
# running (no live server → no-op).
#
# SANCTIONED-BASH-PREFILTER: the ONE piece of logic allowed here. The matcher
# fires this shim on EVERY Bash command; spawning the Python CLI (~0.3s cold
# start) each time is the reason Bash used to be excluded outright. A pure-bash
# token check skips the CLI for payloads that cannot possibly be a search.
# False positives (e.g. "grep" inside a quoted string) just invoke the CLI,
# which decides correctly — fail-open either way. Non-Bash payloads always go
# to the CLI.
#
# Fail-soft: never block a call. CLI absent from PATH — or present but too old
# to have the `hook` command — must no-op silently. So swallow a failing `hook`
# call (stderr hidden) and exit 0.
command -v brainpalace >/dev/null 2>&1 || exit 0
input="$(cat 2>/dev/null || true)"
if [[ "$input" =~ \"tool_name\"[[:space:]]*:[[:space:]]*\"Bash\" ]]; then
  [[ "$input" =~ (^|[^[:alnum:]_.-])(grep|egrep|fgrep|rg|ag)([^[:alnum:]_.-]|$) ]] || exit 0
fi
printf '%s' "$input" | brainpalace hook pretooluse "$@" 2>/dev/null || exit 0
