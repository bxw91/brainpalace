"""Detect whether the BrainPalace Claude Code plugin is installed.

Detection contract (mirrored in the server — keep both in sync):
1. PRIMARY: parse ~/.claude/plugins/installed_plugins.json; true if any plugin
   key's name (the part before '@') == "brainpalace".
2. FALLBACK (registry missing/unparseable): EXPLICIT install dirs only
   (``~/.claude/plugins/brainpalace`` or ``<project>/.claude/plugins/brainpalace``).
   A marketplace cache clone is NOT treated as installed.

``brainpalace init`` writes ``mode: subagent`` (summarization only inside Claude
Code). This contract still reconciles hooks by plugin presence, and the opt-in
``mode: auto`` engine uses it to decide subagent-vs-provider at runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import click


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
    # Registry unreadable → fall back to EXPLICIT install dirs only. A plugin
    # cached under a marketplace clone (``cache/<name>-marketplace/brainpalace``)
    # is NOT an installed plugin — adding a marketplace must never read as
    # installed, so the cache is deliberately not consulted here.
    roots = [home / ".claude" / "plugins" / "brainpalace"]
    if project:
        roots.append(project / ".claude" / "plugins" / "brainpalace")
    return any(r.is_dir() for r in roots)


@click.group("plugin")
def plugin_group() -> None:
    """Inspect the BrainPalace Claude Code plugin.

    \b
    Commands:
      status - Report whether the plugin is installed
    """
    pass


@plugin_group.command("status")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def plugin_status(json_output: bool) -> None:
    """Report whether the BrainPalace Claude Code plugin is installed.

    Single source of truth for detection (shared with setup.sh, which parses
    the --json output instead of re-implementing the registry/dir checks).

    \b
    Examples:
      brainpalace plugin status            # human-readable
      brainpalace plugin status --json     # {"installed": true|false}
    """
    installed = claude_plugin_installed()
    if json_output:
        click.echo(json.dumps({"installed": installed}))
    elif installed:
        click.echo("BrainPalace Claude Code plugin: installed")
    else:
        click.echo("BrainPalace Claude Code plugin: not installed")
