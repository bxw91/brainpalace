#!/bin/bash
# BrainPalace PostToolUse doc-verify nudge — REPO-DEV ONLY (Layer B).
#
# Unlike the doc-SYNC shim next to this file, this hook carries its logic INLINE
# instead of delegating to `brainpalace hook ...`. Reason: `verify-docs` is
# repo-development tooling (see CLAUDE.md → "Shipped plugin vs repo-dev tooling").
# Its nudge MUST NOT ship in the end-user CLI, so it lives entirely here in the
# repo's .claude scope and never reaches an installed CLI.
#
# Fires when an AUDITED DOC is edited: a soft reminder that Layer B prose
# verification is required at the done-boundary (the `task before-push`
# `lint:doc-verify` marker gate blocks until `/brainpalace-verify-docs --changed`
# has been run for the current diff). Non-blocking, no model call, fail-soft.
command -v python3 >/dev/null 2>&1 || exit 0
# The hook payload arrives on THIS script's stdin; capture it and hand it to
# python via env (the heredoc below is python's *program*, so its stdin can't
# also carry the payload).
PAYLOAD="$(cat)" python3 <<'PY'
import json, os, re
try:
    payload = json.loads(os.environ.get("PAYLOAD") or "{}")
    path = (payload.get("tool_input") or {}).get("file_path", "") or ""
    # Audited doc surfaces (mirror scripts/check_doc_freshness.py DEFAULT_GLOBS
    # + standalone files). A pure code edit is caught by the before-push gate, so
    # the per-edit nudge stays focused on prose.
    audited = bool(re.search(
        r"(^|/)(docs/[^/]+\.md"
        r"|brainpalace-plugin/commands/[^/]+\.md"
        r"|brainpalace-plugin/agents/[^/]+\.md"
        r"|brainpalace-plugin/skills/[^/]+/(SKILL|references/[^/]+)\.md"
        r"|brainpalace-plugin/README\.md"
        r"|README\.md|CLAUDE\.md|AGENTS\.md)$",
        path,
    ))
    if audited:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    "Audited doc edited — Layer B prose verification will be "
                    "REQUIRED before push. At the done-boundary (after "
                    "`sync-docs --fix`), run `/brainpalace-verify-docs --changed` "
                    "(the doc-verifier agent) to judge the affected docs vs the "
                    "live code; `task before-push` (lint:doc-verify) blocks until "
                    "the current diff is verified. Don't run it per-edit."
                ),
            }
        }))
except Exception:
    pass  # a hook must NEVER crash or block a session
PY
