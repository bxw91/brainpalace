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
# Fail-soft: never block a session. CLI absent from PATH — or present but too old
# to have the `hook` command (plugin newer than the installed CLI) — must no-op
# silently, not surface an error this UserPromptSubmit hook turns into a block. So
# swallow a failing `hook` call (stderr hidden) and exit 0.
command -v brainpalace >/dev/null 2>&1 || exit 0
brainpalace hook userpromptsubmit "$@" 2>/dev/null || exit 0
