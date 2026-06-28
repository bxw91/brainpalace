"""Commands that intentionally have no plugin doc. Every entry needs a reason —
same closed-loop discipline as dashboard coverage_maps.py."""

from __future__ import annotations

UNDOCUMENTED_COMMANDS: dict[str, str] = {
    "hook": "hidden: internal SessionStart dispatcher, not user-facing",
    "submit-session": "hidden: internal session-submit shim",
    "backfill-sessions": "maintenance one-off, not a plugin command",
    "session-path": "internal path helper",
    "dump-interface": "doc-sync introspection helper, not user-facing",
    "sync-docs": "doc-sync maintenance command, not a plugin command",
    "verify-docs": "doc-verifier (Layer B) maintenance command, repo-dev only "
    "(its agent + command live in .claude/, not the shipped plugin)",
}

# Intentionally documented deprecated aliases (resolution I): alias -> canonical.
DOCUMENTED_ALIASES: dict[str, str] = {}

# Plugin slash-command docs (brainpalace-plugin/commands/) that are NOT mirrors of a
# CLI subcommand — they drive a Claude Code agent workflow and have no `brainpalace
# <name>` command. The CLI-commands checker must not treat them as EXTRA drift or
# gate their frontmatter against a (non-existent) CLI contract. Keyed by doc stem
# (the `<name>` in brainpalace-<name>.md). Every entry needs a reason.
PLUGIN_ONLY_COMMAND_DOCS: dict[str, str] = {
    "setup": "plugin slash-command /brainpalace-setup (setup-assistant agent); "
    "no CLI subcommand — orchestrates install/config/init/verify",
    "install": "plugin slash-command /brainpalace-install (setup-assistant agent); "
    "no CLI subcommand — guided install flow",
    "verify": "plugin slash-command /brainpalace-verify (setup-assistant agent); "
    "no CLI subcommand — guided install/config verification",
    "extract-session": "plugin slash-command /brainpalace-extract-session "
    "(chat-session-extractor agent); manual runtime-agnostic session extraction — "
    "no CLI subcommand, submits via `brainpalace submit-session`",
}

# Plugin docs the PluginDocsChecker (plugin-docs surface) must NOT gate, keyed by
# repo-relative path. Every entry names the gate that already owns the file, so an
# exemption is reviewable and goes stale loudly if that other gate is removed.
PLUGIN_DOC_GATE_EXEMPT: dict[str, str] = {
    "brainpalace-plugin/skills/using-brainpalace/SKILL.md": "generated from "
    "brainpalace-cli/brainpalace_cli/data/ai_guidance.md; gated by "
    "lint:ai-guidance-parity (must not be hand-edited or double-owned here)",
}
