#!/bin/bash
# Note: runs in Claude Code's hook env; no-ops if 'brainpalace' is not on PATH.
# UserPromptSubmit drain hook for Claude Code (BrainPalace) — Phase 080.
#
# Drains the per-project session-summarization gap AFTER the first user turn of a
# session (NOT at startup). Summarization is archive-driven: `drain-queue` selects
# the archived sessions still needing it (new / resumed-and-grown / unmarked, once
# quiescent) — no SessionEnd queue. This hook asks the CLI to drain a bounded batch
# and hands it to the in-session model so the free `chat-session-extractor`
# subagent (pinned to Haiku) distils each. No metered API spend.
#
# Throttling lives in `brainpalace drain-queue` (so it is unit-tested, not in
# bash): a per-turn byte budget + count cap bound one batch, first-pick-always
# means a single oversized session drains alone, and a 5-min cooldown paces
# repeated prompts so a big backlog trickles out over active working time +
# across sessions instead of clogging one turn.
#
# Why UserPromptSubmit (not SessionStart)?
#   Extraction should wait until the user has actually begun working, not fire at
#   session START. UserPromptSubmit fires on every prompt; the cooldown inside
#   drain-queue keeps repeated prompts from re-draining.
#
# The queue is DURABLE: a pending session_id survives until a later drain,
# however much later. Nothing is lost.
#
# Output contract (Claude Code injects `additionalContext` into the turn):
#   {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
#                           "additionalContext": "<directive>"}}
# When the queue is empty we print nothing and exit 0 (no injection).
#
# Install (one-time):
#   1. cp userpromptsubmit-drain-hook.sh \
#        ~/.claude/hooks/brainpalace-userpromptsubmit-drain.sh
#      chmod +x ~/.claude/hooks/brainpalace-userpromptsubmit-drain.sh
#   2. In ~/.claude/settings.json under hooks.UserPromptSubmit:
#        {
#          "hooks": {
#            "UserPromptSubmit": [
#              { "hooks": [ {
#                  "type": "command",
#                  "command": "bash ~/.claude/hooks/brainpalace-userpromptsubmit-drain.sh",
#                  "timeout": 5
#              } ] }
#            ]
#          }
#        }
#   3. Pair with the SessionEnd hook (queues) + SessionStart hook (reminder).
#
# Privacy: only drains for projects BrainPalace has indexed (whoami gate).

# Bail silently if the CLI is not installed.
command -v brainpalace >/dev/null 2>&1 || exit 0

# Whoami exit-code gate: 0=running, 2=indexed-not-running both proceed; 1=no
# project found → silently no-op so non-indexed projects are never touched.
brainpalace whoami >/dev/null 2>&1
code=$?
if [ "$code" -ne 0 ] && [ "$code" -ne 2 ]; then
    exit 0
fi

# Resolve project root from whoami ("Project: <path>").
project="$(brainpalace whoami 2>/dev/null | awk -F': ' '/^Project:/{print $2; exit}')"
[ -n "$project" ] || project="$(pwd)"
# Drain a bounded, cooldown-paced batch via the CLI (logic + throttling live
# there). Empty queue / active cooldown ⇒ drained=[] ⇒ inject nothing.
out="$(brainpalace drain-queue --project "$project" --json 2>/dev/null)" || exit 0
[ -n "$out" ] || exit 0

python3 - "$out" <<'PY'
import json, sys
try:
    res = json.loads(sys.argv[1])
except (ValueError, IndexError):
    sys.exit(0)
ids = res.get("drained") or []
if not ids:
    sys.exit(0)
remaining = int(res.get("remaining", 0) or 0)
tail = f" ({remaining} more queued — draining gradually.)" if remaining else ""
directive = (
    "Prior sessions are pending knowledge extraction: "
    + " ".join(ids)
    + ". Run the chat-session-extractor subagent on each (it submits via "
    "`brainpalace submit-session`). Best-effort background curation — do it "
    "alongside the user's request, don't block on it." + tail
)
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": directive,
    }
}))
PY
