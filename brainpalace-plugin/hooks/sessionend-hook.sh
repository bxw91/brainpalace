#!/bin/bash
# Note: runs in Claude Code's hook env; no-ops if 'brainpalace' is not on PATH.
# SessionEnd hook for Claude Code (BrainPalace) — queue-and-drain extraction.
#
# Claude Code SessionEnd hooks are shell-only: they cannot run an LLM for free
# at end-of-session. So this hook does the cheap half — it appends the
# just-ended session_id to a per-project queue file. The companion SessionStart
# hook drains that queue by asking the (already-running, subscription-tier)
# in-session model to run the `chat-session-extractor` subagent. No metered API
# spend; extraction happens at the next session start.
#
# Queue file: <project>/.brainpalace/extract-queue.txt (one session_id/line).
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

# Only queue for indexed projects (whoami exit 0=running, 2=indexed-not-running).
brainpalace whoami >/dev/null 2>&1
code=$?
if [ "$code" -ne 0 ] && [ "$code" -ne 2 ]; then
    exit 0
fi

# Resolve the project root from whoami ("Project: <path>").
project="$(brainpalace whoami 2>/dev/null | awk -F': ' '/^Project:/{print $2; exit}')"
[ -n "$project" ] || project="$(pwd)"
state_dir="$project/.brainpalace"
[ -d "$state_dir" ] || exit 0

queue="$state_dir/extract-queue.txt"

# Dedup: skip if already queued.
if [ -f "$queue" ] && grep -qxF "$session_id" "$queue" 2>/dev/null; then
    exit 0
fi
printf '%s\n' "$session_id" >>"$queue"

# Cap the queue at the most recent 50 entries.
if [ -f "$queue" ] && [ "$(wc -l <"$queue")" -gt 50 ]; then
    tail -n 50 "$queue" >"$queue.tmp" && mv "$queue.tmp" "$queue"
fi

exit 0
