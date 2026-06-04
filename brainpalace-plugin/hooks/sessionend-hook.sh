#!/bin/bash
# Note: runs in Claude Code's hook env; no-ops if 'brainpalace' is not on PATH.
# SessionEnd hook for Claude Code (BrainPalace) — retired queue (kept as no-op).
#
# Summarization is now ARCHIVE-DRIVEN: the file watcher copies every session into
# `.brainpalace/session_archive/`, and `brainpalace drain-tick`/`drain-queue`
# summarize the archived sessions still needing it (gap = archive ∖ fresh `.done`
# markers), gated by quiescence. There is no SessionEnd queue to append to, so
# this hook does nothing but keep its install footprint (it still ships in
# plugin.json). Left in place so existing settings.json entries stay valid.
#
# Install (one-time):
#   1. cp sessionend-hook.sh ~/.claude/hooks/brainpalace-sessionend.sh
#      chmod +x ~/.claude/hooks/brainpalace-sessionend.sh
#   2. In ~/.claude/settings.json under hooks.SessionEnd:
#        {
#          "hooks": {
#            "SessionEnd": [
#              { "hooks": [ {
#                  "type": "command",
#                  "command": "bash ~/.claude/hooks/brainpalace-sessionend.sh",
#                  "timeout": 5
#              } ] }
#            ]
#          }
#        }
#   3. Pair with the SessionStart hook (drains the queue). Restart Claude Code.
#
# Privacy: only queues for projects BrainPalace has indexed. Extraction itself
# (next session start) submits distilled content only, and only runs when
# session indexing is enabled for the project.

# Bail silently if the CLI is not installed.
command -v brainpalace >/dev/null 2>&1 || exit 0

# Read the hook payload (JSON on stdin) — extract session_id. Tolerate missing.
payload="$(cat 2>/dev/null)"
session_id="$(printf '%s' "$payload" | python3 -c 'import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get("session_id") or "")
except Exception:
    print("")
' 2>/dev/null)"

[ -n "$session_id" ] || exit 0

# Only act for indexed projects (whoami exit 0=running, 2=indexed-not-running).
brainpalace whoami >/dev/null 2>&1
code=$?
if [ "$code" -ne 0 ] && [ "$code" -ne 2 ]; then
    exit 0
fi

# Phase 09x: queue retired — summarization is archive-driven (brainpalace
# drain-tick). Nothing to append; the archive + gap-selector are the source of
# truth. This hook is intentionally a no-op past the whoami gate.
exit 0
