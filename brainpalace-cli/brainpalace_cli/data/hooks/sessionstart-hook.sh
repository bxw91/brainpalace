#!/bin/bash
# Conditional SessionStart hook for Claude Code (BrainPalace).
#
# Emits a "prefer brainpalace query" reminder ONLY when the current project
# has an `.brainpalace/` index. Silently no-op otherwise — so non-indexed
# projects are not forced to use BrainPalace.
#
# Why this matters:
#   An unconditional SessionStart reminder that tells the AI "BrainPalace
#   FIRST" fires in every project, even ones without an `.brainpalace/`
#   directory. The AI then tries `brainpalace query`, the CLI errors out,
#   and the user (who never set BrainPalace up) is left confused. This
#   template gates the reminder on `brainpalace whoami` exit code, which
#   walks up the directory tree looking for `.brainpalace/`.
#
# Whoami exit codes (contract):
#   0  project found + server running
#   1  no `.brainpalace/` in CWD or any ancestor   ← skip reminder
#   2  project found but server not running        ← still emit reminder
#
# Install (one-time):
#   1. Copy this file to a stable location, e.g.
#        cp sessionstart-hook.sh ~/.claude/hooks/brainpalace-sessionstart.sh
#        chmod +x ~/.claude/hooks/brainpalace-sessionstart.sh
#
#   2. Reference it from `~/.claude/settings.json` under hooks.SessionStart:
#        {
#          "hooks": {
#            "SessionStart": [
#              {
#                "hooks": [
#                  {
#                    "type": "command",
#                    "command": "bash ~/.claude/hooks/brainpalace-sessionstart.sh",
#                    "timeout": 3
#                  }
#                ]
#              }
#            ]
#          }
#        }
#
#   3. Restart Claude Code. Reminder will appear only in indexed projects.

# Bail silently if the CLI is not installed.
command -v brainpalace >/dev/null 2>&1 || exit 0

# Run whoami; capture exit code. Suppress all output — we only care about the code.
brainpalace whoami >/dev/null 2>&1
code=$?

# Exit code 1 = no project found. Silently no-op so non-indexed projects
# are NOT forced to use BrainPalace.
if [ "$code" -eq 1 ]; then
    exit 0
fi

migration_note=""
session_context=""
if [ "$code" -eq 0 ]; then
    # Phase 035: inject the frozen-snapshot context block (project facts +
    # curated memory). Fail soft — never block session start if it errors.
    session_context="$(brainpalace context 2>/dev/null || true)"
fi

# Phase 080: session-extraction queue draining moved OUT of SessionStart into
# `userpromptsubmit-drain-hook.sh`. Extraction must fire AFTER the first user
# turn, not at startup — so the drain now lives on UserPromptSubmit.

# Exit codes 0 (server up) and 2 (server down but project indexed) both emit
# the reminder. For code 2, the reminder is still useful — it tells the AI
# the project IS indexed so it should start the server rather than fall back
# to native search.
python3 - "$migration_note" "$session_context" <<'PY'
import json, sys
note = sys.argv[1] if len(sys.argv) > 1 else ""
context = sys.argv[2] if len(sys.argv) > 2 else ""
msg = (
    "BrainPalace is indexed for this project — prefer `brainpalace query` "
    "over Glob/Grep for codebase search. If the server is not running, "
    "start it with `brainpalace start`. "
    "`brainpalace query --json` result keys are text/source/score/chunk_id "
    "(no file_path, no line numbers); on failure stdout is "
    '{"error": ...} with no "results" key and a non-zero exit — check for '
    "it, and never append 2>/dev/null to brainpalace commands."
    + note
)
if context.strip():
    # Frozen snapshot: loaded once at session start (Phase 035). Mid-session
    # memory writes take effect next session.
    msg += "\n\n" + context.strip()
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": msg,
    }
}))
PY
