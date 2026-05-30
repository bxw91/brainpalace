#!/bin/bash
# OPT-IN weekly memory-curate hook for Claude Code (BrainPalace, Phase 080).
#
# At most once per ISO week, asks the in-session (subscription-tier) model to
# run the `memory-curator` subagent in "weekly curate" mode: prune stale /
# merge duplicate curated memories and enforce caps (Phase 030). No metered
# API, no cron.
#
# SessionStart hook gated by a per-project ISO-week stamp.
#
# Install (opt-in):
#   cp weekly-curate-hook.sh ~/.claude/hooks/brainpalace-weekly-curate.sh
#   chmod +x ~/.claude/hooks/brainpalace-weekly-curate.sh
#   Add another SessionStart entry in ~/.claude/settings.json pointing at it.

command -v brainpalace >/dev/null 2>&1 || exit 0

brainpalace whoami >/dev/null 2>&1
code=$?
[ "$code" -eq 0 ] || [ "$code" -eq 2 ] || exit 0

project="$(brainpalace whoami 2>/dev/null | awk -F': ' '/^Project:/{print $2; exit}')"
[ -n "$project" ] || project="$(pwd)"
state_dir="$project/.brainpalace"
[ -d "$state_dir" ] || exit 0

stamp="$state_dir/.weekly-curate-stamp"
week="$(date +%G-W%V)"  # ISO year + week number
[ -f "$stamp" ] && [ "$(cat "$stamp" 2>/dev/null)" = "$week" ] && exit 0
printf '%s' "$week" >"$stamp"

python3 - <<'PY'
import json
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": (
            "Weekly memory upkeep (best-effort, don't block the user): run the "
            "memory-curator subagent in weekly-curate mode — obsolete superseded "
            "memories, delete duplicates, and keep curated memory under its cap "
            "via `brainpalace memories list|obsolete|delete`."
        ),
    }
}))
PY
