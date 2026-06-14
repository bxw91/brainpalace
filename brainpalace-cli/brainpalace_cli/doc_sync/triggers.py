"""Interface-source paths whose edit should nudge a doc-sync. Editing these can change
the interface; editing docs/tests should NOT re-trigger (base-spec §1, P2)."""

from __future__ import annotations

import fnmatch

INTERFACE_SOURCE_GLOBS = (
    "*/brainpalace_cli/cli.py",
    "*/brainpalace_cli/commands/*",
    "*/brainpalace_cli/config_schema.py",
    "*/brainpalace_cli/mcp_server/server.py",
    "*/brainpalace_server/api/*",
    "brainpalace-plugin/skills/*",
)


def is_interface_source(path: str) -> bool:
    norm = path.replace("\\", "/")
    # exclude tests and the command DOCS (those are outputs, not interface sources)
    if "/tests/" in norm or norm.startswith("brainpalace-plugin/commands/"):
        return False
    return any(
        fnmatch.fnmatch(norm, g) or fnmatch.fnmatch(norm, f"*/{g}")
        for g in INTERFACE_SOURCE_GLOBS
    )
