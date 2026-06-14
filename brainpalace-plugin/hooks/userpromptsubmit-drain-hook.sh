#!/bin/bash
# BrainPalace UserPromptSubmit drain hook — THIN SHIM. Do NOT add logic here.
#
# All behavior + injected text live in the CLI (`brainpalace hook
# userpromptsubmit`), so a `pip`/CLI upgrade propagates every change without
# rewriting this file — the shim contains nothing version-specific and cannot go
# stale. See CLAUDE.md → "AI-guidance parity" and the sessionstart-hook for the
# pattern.
#
# Drains the per-project session-summarization gap AFTER a user turn (NOT at
# startup): selection, byte budget, count cap, and the 5-min cooldown live in
# `drain-queue`; on a non-empty drain the CLI injects a directive asking the
# in-session model to run the free `chat-session-extractor` subagent. Indexed
# projects only; empty drain / active cooldown → emit nothing.
#
# Fail-soft: if the CLI is not on PATH, no-op silently (never block a session).
command -v brainpalace >/dev/null 2>&1 || exit 0
exec brainpalace hook userpromptsubmit "$@"
