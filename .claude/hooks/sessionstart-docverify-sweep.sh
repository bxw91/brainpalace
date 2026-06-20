#!/bin/bash
# BrainPalace SessionStart weekly doc-verify sweep reminder — REPO-DEV ONLY.
#
# Layer B (prose verification) is advisory + probabilistic + costs subscription,
# so it is NOT a push gate. Instead the repo reminds you to run a sweep at most
# ONCE A WEEK, on its own (no system cron): this SessionStart hook checks a local
# cadence file and, when a week has passed since the last verification AND since
# the last reminder, injects a nudge asking the AI to offer running the sweep.
#
# Cadence file (gitignored, per-machine): .claude/.doc-verify-sweep.json
#   { "last_verify": "YYYY-MM-DD", "last_prompt": "YYYY-MM-DD" }
# - last_verify is stamped by `brainpalace verify-docs --record` (any verify run
#   resets the weekly clock).
# - last_prompt is stamped HERE when we decide to remind (dedupes multiple
#   sessions in the same week; on a user refusal the next reminder is +7 days).
#
# Non-blocking, no model call, fail-soft: a hook must never crash a session.
command -v python3 >/dev/null 2>&1 || exit 0
cat >/dev/null 2>&1  # drain the SessionStart payload on stdin (unused)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}" \
PERIOD_DAYS=7 \
python3 <<'PY'
import json, os
from datetime import date

proj = os.environ.get("PROJECT_DIR") or "."
period = int(os.environ.get("PERIOD_DAYS", "7"))
state_path = os.path.join(proj, ".claude", ".doc-verify-sweep.json")
today = date.today()

def days_since(s):
    if not s:
        return 10**6  # never -> always due
    try:
        return (today - date.fromisoformat(s)).days
    except Exception:
        return 10**6

try:
    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    if not isinstance(state, dict):
        state = {}
except Exception:
    state = {}

since_verify = days_since(state.get("last_verify"))
since_prompt = days_since(state.get("last_prompt"))

# Due only when a full period has passed since BOTH the last verification and the
# last reminder. The second clause is what makes a refusal repeat next week, not
# next session.
if since_verify >= period and since_prompt >= period:
    # Stamp the reminder now so other sessions this week stay silent, regardless
    # of whether the user accepts or declines.
    state["last_prompt"] = today.isoformat()
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
    except Exception:
        pass  # fail-soft: never block the session over cadence bookkeeping

    last = state.get("last_verify") or "never"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "WEEKLY DOC-VERIFY SWEEP DUE (repo-dev, advisory). Doc prose has "
                f"not been verified vs live code in >= {period} days (last: {last}). "
                "ASK THE USER (one question, AskUserQuestion) whether to run the "
                "Layer B prose sweep now via `/brainpalace-verify-docs --all` — the "
                "FULL baseline, the only mode that catches latent drift already in "
                "main with no current diff (`--changed` structurally cannot). "
                "Relation-driven skipping + the verdict cache keep it cheap: it "
                "re-judges only docs whose prose or grounded code changed and "
                "reuses cached verdicts for "
                "unchanged claims, so an all-fresh empty packet is normal. Dispatch "
                "the Sonnet-pinned doc-verifier, walking the set in small batches. "
                "If YES, run it — `verify-docs --record` re-stamps the weekly clock. "
                "If NO, do nothing: this reminder will repeat next week. Do not run "
                "it without asking, and do not block the user's current task on it."
            ),
        }
    }))
PY
exit 0
