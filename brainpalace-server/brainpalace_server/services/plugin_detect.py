"""Detect whether the BrainPalace Claude Code plugin is installed.

MIRROR of brainpalace-cli's brainpalace_cli/commands/plugin_detect.py — keep
both in sync (documented contract; no cross-package import).

Detection contract:
1. PRIMARY: parse ~/.claude/plugins/installed_plugins.json; true if any plugin
   key's name (the part before '@') == "brainpalace".
2. FALLBACK (registry missing/unparseable): directory checks.

The server uses this in `auto` mode: when the plugin is present it defers
extraction to the plugin (with a 24h safety net); when absent it distils itself.
"""

from __future__ import annotations

import json
from pathlib import Path


def _registry_has_brainpalace(home: Path) -> bool | None:
    """True/False from the CC registry; None if it can't be read/parsed."""
    reg = home / ".claude" / "plugins" / "installed_plugins.json"
    if not reg.is_file():
        return None
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
        plugins = data.get("plugins", {})
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    return any(str(key).split("@", 1)[0] == "brainpalace" for key in plugins)


def claude_plugin_installed(
    home: Path | None = None, project: Path | None = None
) -> bool:
    home = home or Path.home()
    reg = _registry_has_brainpalace(home)
    if reg is not None:
        return reg
    roots = [home / ".claude" / "plugins" / "brainpalace"]
    if project:
        roots.append(project / ".claude" / "plugins" / "brainpalace")
    if any(r.is_dir() for r in roots):
        return True
    cache = home / ".claude" / "plugins" / "cache"
    return cache.is_dir() and any(cache.glob("*/brainpalace"))
