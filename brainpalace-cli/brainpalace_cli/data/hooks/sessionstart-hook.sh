#!/bin/bash
# BrainPalace SessionStart hook — THIN SHIM. Do NOT add logic here.
#
# All behavior + injected text live in the CLI (`brainpalace hook sessionstart`),
# so a `pip`/CLI upgrade propagates every change without rewriting this file —
# the shim contains nothing version-specific and cannot go stale. See
# CLAUDE.md → "AI-guidance parity".
#
# Fail-soft: never block a session. CLI present but too old to have the `hook`
# command (plugin newer than the installed CLI) must no-op silently, not surface
# an error a UserPromptSubmit/PreToolUse hook turns into a block. So swallow a
# failing `hook` call (stderr hidden) and exit 0.
#
# SANCTIONED-CLI-MISSING-NUDGE: the one branch that legitimately carries injected
# text in the shim. When `brainpalace` is absent from PATH the CLI cannot announce
# its own absence, so the plugin must — the engine that owns every other message
# is the very thing that is missing. Emit a single SessionStart directive asking
# the model to offer installation, then exit 0. check_ai_guidance_parity.py allows
# the `additionalContext` token ONLY inside a shim that carries this marker.
if ! command -v brainpalace >/dev/null 2>&1; then
  # Honor the documented opt-out. Otherwise fire EVERY session while the CLI is
  # absent — a stateless reminder that persists even if the user declined before,
  # so BrainPalace never silently stays broken.
  case "${BRAINPALACE_SETUP_NUDGE:-}" in
    off | false | 0 | disabled) exit 0 ;;
  esac
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"The BrainPalace plugin is loaded but its CLI engine is not installed, so the plugin cannot function. Before anything else, call the AskUserQuestion tool. Keep the card simple and decisive: question = BrainPalace CLI is not installed and the plugin cannot work without it. Install now? Three short options: Full setup (runs /brainpalace-setup), CLI only (runs /brainpalace-install), Skip. Do not add extra prose to the card. Silence with BRAINPALACE_SETUP_NUDGE=off."}}'
  exit 0
fi
brainpalace hook sessionstart "$@" 2>/dev/null || exit 0
