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
from typing import Any

import click

#: Repo + endpoints used to tell the user whether their installed plugin is
#: behind. We read the plugin manifest at the LATEST GitHub RELEASE tag (not
#: ``main``, which can run ahead of what users can actually install). Network
#: reads — always fail-soft.
GITHUB_REPO = "bxw91/brainpalace"
GITHUB_LATEST_RELEASE_URL = (
    f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
)
PLUGIN_JSON_RAW_TEMPLATE = (
    "https://raw.githubusercontent.com/"
    + GITHUB_REPO
    + "/{ref}/brainpalace-plugin/.claude-plugin/plugin.json"
)


def _registry_brainpalace_entry(home: Path) -> tuple[str, dict[str, Any]] | None:
    """``(qualified_key, entry)`` for the installed brainpalace plugin, else None.

    ``qualified_key`` is the registry key (e.g. ``brainpalace@brainpalace-marketplace``)
    — the exact name ``claude plugin update`` needs.
    """
    reg = home / ".claude" / "plugins" / "installed_plugins.json"
    if not reg.is_file():
        return None
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
        plugins = data.get("plugins", {})
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    for key, entries in plugins.items():
        if str(key).split("@", 1)[0] != "brainpalace":
            continue
        entry = entries[0] if isinstance(entries, list) and entries else entries
        if isinstance(entry, dict):
            return str(key), entry
    return None


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


def _read_plugin_json_version(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        v = data.get("version")
        return str(v) if v else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def installed_plugin_version(home: Path | None = None) -> str | None:
    """Installed plugin version from the CC registry; fall back to the explicit
    install dir's plugin.json. ``None`` when not installed / unknown."""
    home = home or Path.home()
    ent = _registry_brainpalace_entry(home)
    if ent and ent[1].get("version"):
        return str(ent[1]["version"])
    return _read_plugin_json_version(
        home / ".claude" / "plugins" / "brainpalace" / ".claude-plugin" / "plugin.json"
    )


def plugin_update_target(home: Path | None = None) -> str:
    """Qualified ``<plugin>@<marketplace>`` name for ``claude plugin update``.

    Derived from the registry key so the printed command matches the user's
    actual marketplace; defaults to the canonical name when unknown.
    """
    home = home or Path.home()
    ent = _registry_brainpalace_entry(home)
    return ent[0] if ent else "brainpalace@brainpalace-marketplace"


def _latest_release_ref(timeout: float) -> str | None:
    """Tag of the latest GitHub release, or ``None`` if it can't be read."""
    import httpx  # local dep already used by the client

    resp = httpx.get(
        GITHUB_LATEST_RELEASE_URL,
        timeout=timeout,
        headers={"Accept": "application/vnd.github+json"},
    )
    resp.raise_for_status()
    tag = resp.json().get("tag_name")
    return str(tag) if tag else None


def available_plugin_version(timeout: float = 3.0) -> str | None:
    """Plugin version from the LATEST GitHub RELEASE (the manifest at that tag),
    not ``main``. ``None`` on any failure (offline, no release yet, timeout,
    parse error) — callers must treat it as unknown."""
    try:
        import httpx  # local dep already used by the client

        ref = _latest_release_ref(timeout)
        if not ref:
            return None
        resp = httpx.get(PLUGIN_JSON_RAW_TEMPLATE.format(ref=ref), timeout=timeout)
        resp.raise_for_status()
        v = resp.json().get("version")
        return str(v) if v else None
    except Exception:
        return None


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in v.split("."))
    except (ValueError, AttributeError):
        return ()


def plugin_update_available(installed: str | None, available: str | None) -> bool:
    """True when ``available`` is a newer plugin version than ``installed``.

    CalVer ``YY.M.N`` compares numerically; on a non-numeric version it falls
    back to inequality. Either side unknown → False (never nag without data).
    """
    if not installed or not available:
        return False
    ti, ta = _version_tuple(installed), _version_tuple(available)
    if ti and ta:
        return ta > ti
    return available != installed


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


def claude_code_present(home: Path | None = None) -> bool:
    """True when Claude Code is set up for this user (a ``~/.claude`` directory)."""
    home = home or Path.home()
    return (home / ".claude").is_dir()


#: Short, shown when Claude Code is present but the plugin is not installed. The
#: plugin is the single delivery vehicle for the Claude Code integration
#: (subagent guard, research agent, search guidance) — the CLI deliberately does
#: NOT install those, to avoid a second copy drifting from ``plugin.json``.
PLUGIN_INSTALL_HINT = (
    "Tip: install the BrainPalace Claude Code plugin for the full integration "
    "(research agent, subagent guard, search guidance):\n"
    "  /plugin marketplace add bxw91/brainpalace\n"
    "  /plugin install brainpalace\n"
    "Already installed? Update with the QUALIFIED name (the bare name fails):\n"
    "  claude plugin update brainpalace@brainpalace-marketplace\n"
    "The CLI alone does not wire those into Claude Code."
)


def maybe_plugin_hint(home: Path | None = None) -> str:
    """Return the install hint when Claude Code is present but the plugin is not.

    Empty string otherwise (no Claude Code, or plugin already installed).
    """
    home = home or Path.home()
    if claude_code_present(home) and not claude_plugin_installed(home):
        return PLUGIN_INSTALL_HINT
    return ""


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
    inst_ver = installed_plugin_version() if installed else None
    avail_ver = available_plugin_version() if installed else None
    behind = plugin_update_available(inst_ver, avail_ver)
    if json_output:
        click.echo(
            json.dumps(
                {
                    "installed": installed,
                    "version": inst_ver,
                    "latest": avail_ver,
                    "update_available": behind,
                }
            )
        )
    elif not installed:
        click.echo("BrainPalace Claude Code plugin: not installed")
    else:
        line = f"BrainPalace Claude Code plugin: installed {inst_ver or 'unknown'}"
        if behind:
            line += f"  ->  {avail_ver} available"
        elif avail_ver:
            line += "  (up to date)"
        click.echo(line)
        if behind:
            click.echo(f"  Update: claude plugin update {plugin_update_target()}")
