#!/usr/bin/env bash
# PreToolUse / Bash guard — block `task before-push` outside the release boundary.
#
# Repo-dev tooling (project scope, NOT the shipped plugin). `before-push` is the
# RELEASE-boundary gate (~10 min): run ONCE on stable's tip before the squash-mirror
# to main (docs/RELEASING.md step 8). It is NOT an inner-loop / per-commit /
# per-feature->stable-merge check — those are local, not pushes. This guard stops
# auto-generated plans and reflexive runs from invoking the 10-min gate mid-dev.
#
# Override (deliberate release run), either form:
#   BRAINPALACE_RELEASE=1 task before-push      # inline (matched in the command)
#   export BRAINPALACE_RELEASE=1                # session-wide (matched in env)
#
# Fail-soft: any parsing problem -> allow (never wedge the session). The gate
# itself is still the real safety net at release time.
set -euo pipefail

input="$(cat 2>/dev/null || true)"

# Extract the bash command; if jq or the field is missing, allow.
cmd=""
if command -v jq >/dev/null 2>&1; then
  cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
fi
[ -n "$cmd" ] || exit 0

# React only to an actual `task ... before-push` invocation within a single command
# segment (env prefix / flags allowed; not split across && | ;). Mentions in other
# segments (e.g. `task test && echo before-push`) do not match.
if ! printf '%s' "$cmd" | grep -Eq '\btask\b[^&|;]*\bbefore-push\b'; then
  exit 0
fi

# Release opt-in: env var in the hook's environment, or set inline in the command.
if [ "${BRAINPALACE_RELEASE:-}" = "1" ] || printf '%s' "$cmd" | grep -Eq '\bBRAINPALACE_RELEASE=1\b'; then
  exit 0
fi

# Block with an actionable reason fed back to the model.
cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"`task before-push` is the RELEASE-boundary gate (~10 min) — not an inner-loop or per-merge check. A feature->stable merge is LOCAL, not a push, so it does not need this gate. Inner loop: `task format && task check` plus scoped tests (`task test:server` / `task test:cli` / `poetry run pytest <file>`); full local sweep: `task test`. Run the full gate ONCE at the release boundary, on stable's tip before the squash-mirror to main (docs/RELEASING.md step 8): `BRAINPALACE_RELEASE=1 task before-push`."}}
JSON
exit 0
