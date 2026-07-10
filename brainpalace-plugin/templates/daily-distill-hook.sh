#!/bin/bash
# DEPRECATED (retained for non-Claude runtimes / manual use). Daily distil is now
# performed server-side by `promote_decisions` (durable session decisions are
# promoted into curated memory automatically at extraction time, with cap-reclaim
# eviction). This standalone template is no longer the recommended path for
# Claude Code — the auto-wired `brainpalace hook sessionstart` covers it.
#
# OPT-IN daily memory-distil hook for Claude Code (BrainPalace, Phase 080).
#
# At most once per day, asks the in-session (subscription-tier) model to run the
# `memory-curator` subagent in "daily distil" mode: pull durable facts from
# recent sessions into the curated memory (Phase 030). No metered API, no cron.
#
# It is a SessionStart hook gated by a per-project date stamp so it fires only
# the first session of each day. Pair it with the main SessionStart hook (you
# can register multiple SessionStart hooks).
#
# Install (opt-in):
#   cp daily-distill-hook.sh ~/.claude/hooks/brainpalace-daily-distill.sh
#   chmod +x ~/.claude/hooks/brainpalace-daily-distill.sh
#   Add another SessionStart entry in ~/.claude/settings.json pointing at it.

command -v brainpalace >/dev/null 2>&1 || exit 0

brainpalace whoami >/dev/null 2>&1
code=$?
[ "$code" -eq 0 ] || [ "$code" -eq 2 ] || exit 0

project="$(brainpalace whoami 2>/dev/null | awk -F': ' '/^Project:/{print $2; exit}')"
[ -n "$project" ] || project="$(pwd)"
state_dir="$project/.brainpalace"
[ -d "$state_dir" ] || exit 0

stamp="$state_dir/.daily-distill-stamp"
today="$(date +%Y-%m-%d)"
[ -f "$stamp" ] && [ "$(cat "$stamp" 2>/dev/null)" = "$today" ] && exit 0
printf '%s' "$today" >"$stamp"

python3 - <<'PY'
import json
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": (
            "Daily memory upkeep (best-effort, don't block the user): run the "
            "memory-curator subagent in daily-distil mode — pull durable, "
            "reusable facts from recent sessions into curated memory via "
            "`brainpalace remember`. Skip anything transient or already stored."
        ),
    }
}))
PY
