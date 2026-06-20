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
    # Normalise to a repo-relative path so the exclusion match below is robust to an
    # absolute CLAUDE_PROJECT_DIR prefix.
    rel = re.sub(r"^.*?/(?=docs/|brainpalace-plugin/|README\.md|CLAUDE\.md|AGENTS\.md)",
                 "", path)
    audited = bool(re.search(
        r"(^|/)(docs/[^/]+\.md"
        r"|brainpalace-plugin/commands/[^/]+\.md"
        r"|brainpalace-plugin/agents/[^/]+\.md"
        r"|brainpalace-plugin/skills/[^/]+/(SKILL|references/[^/]+)\.md"
        r"|brainpalace-plugin/README\.md"
        r"|README\.md|CLAUDE\.md|AGENTS\.md)$",
        path,
    ))
    # MIRROR verify_docs.py `_is_excluded`: CHANGELOG / ORIGINAL_SPEC (frozen/historical)
    # and the superpowers/.planning trees are NEVER prose-verified. Nudging Layer B for
    # them is a false instruction (the verifier silently skips them). Split the nudge:
    #   * excluded but freshness-audited (CHANGELOG, ORIGINAL_SPEC) → its body hash went
    #     stale; the correct done-boundary act is a freshness RE-STAMP, not a re-ground.
    #   * excluded scratch/plan trees → not audited at all → no nudge.
    EXCLUDE_FILES = {"docs/CHANGELOG.md", "docs/ORIGINAL_SPEC.md"}
    EXCLUDE_PREFIXES = ("docs/superpowers/", ".planning/")
    is_excluded = rel in EXCLUDE_FILES or rel.startswith(EXCLUDE_PREFIXES)

    msg = None
    if is_excluded and rel in EXCLUDE_FILES:
        msg = (
            "Freshness-audited but Layer-B-EXCLUDED doc edited (historical/frozen — "
            "never prose-verified). Do NOT run verify-docs on it. Its doc-freshness "
            "hash is now stale: re-stamp before push — "
            f"`python scripts/add_audit_metadata.py {rel}` (task before-push / "
            "lint:doc-freshness blocks until then)."
        )
    elif audited and not is_excluded:
        msg = (
            "Audited doc edited — Layer B prose verification will be REQUIRED before "
            "push. At the done-boundary (after `sync-docs --fix`), run "
            "`/brainpalace-verify-docs --changed` (the doc-verifier agent) to judge "
            "the affected docs vs the live code; `task before-push` (lint:doc-verify) "
            "blocks until the current diff is verified. Don't run it per-edit."
        )
    if msg:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": msg,
            }
        }))
except Exception:
    pass  # a hook must NEVER crash or block a session
PY
