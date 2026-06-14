"""`install-session-hooks` — install BrainPalace's SessionStart reminder hook.

Writes the SessionStart hook into ``~/.claude/hooks/`` and registers it in
``~/.claude/settings.json``:

  * **SessionStart** — the "prefer ``brainpalace query``" reminder + context.

The two extraction hooks (SessionEnd queue + UserPromptSubmit drain) are now
owned by the Claude Code **plugin** (`plugin.json` `hooks`). This command also
prunes any old extraction hooks a prior version wrote into ``settings.json``, so
upgrading never leaves a double-running pair. Idempotent.
"""

from __future__ import annotations

import copy
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import click

from .plugin_detect import claude_plugin_installed

#: The single event this command installs.
REMINDER_EVENT = "SessionStart"

#: Installed script name → bundled source resource name (``data/hooks/``).
_SOURCES: dict[str, str] = {
    "brainpalace-sessionstart.sh": "sessionstart-hook.sh",
}

#: Claude Code hook event → installed script name.
_EVENT_SCRIPTS: dict[str, str] = {
    "SessionStart": "brainpalace-sessionstart.sh",
}

#: Per-event hook timeouts (seconds).
TIMEOUTS: dict[str, int] = {
    "SessionStart": 3,
}

#: Old extraction-hook script basenames now owned by the plugin — prune them.
_EXTRACTION_SCRIPTS = (
    "brainpalace-sessionend.sh",
    "brainpalace-userpromptsubmit-drain.sh",
)


def prune_extraction_hooks(settings: dict[str, Any]) -> dict[str, Any]:
    """Remove BrainPalace extraction-hook entries (now plugin-owned). Idempotent;
    preserves the user's own hooks and the SessionStart reminder."""
    merged = copy.deepcopy(settings)
    for event, groups in list(merged.get("hooks", {}).items()):
        kept = []
        for g in groups:
            hs = [
                h
                for h in g.get("hooks", [])
                if not any(s in h.get("command", "") for s in _EXTRACTION_SCRIPTS)
            ]
            if hs:
                kept.append({**g, "hooks": hs})
        merged["hooks"][event] = kept
    return merged


def _script_marker(command: str) -> str:
    """The ``*.sh`` basename inside a hook command (used for dedup)."""
    for token in command.split():
        if token.endswith(".sh"):
            return Path(token).name
    return command


def write_hook_scripts(home: Path) -> list[Path]:
    """Write the bundled hook script(s) into ``<home>/.claude/hooks/``.

    Returns the installed script paths. Each is chmod 0755.
    """
    hooks_dir = home / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    resources = files("brainpalace_cli.data.hooks")

    written: list[Path] = []
    for dest_name, src_name in _SOURCES.items():
        content = resources.joinpath(src_name).read_text(encoding="utf-8")
        dest = hooks_dir / dest_name
        dest.write_text(content, encoding="utf-8")
        dest.chmod(0o755)
        written.append(dest)
    return written


#: Marker proving an installed hook is the current thin shim (delegates to the
#: CLI). A legacy "fat" hook embeds its own python/whoami logic instead.
_SHIM_MARKER = "brainpalace hook sessionstart"


def migrate_legacy_sessionstart_hook(home: Path) -> bool:
    """Rewrite an already-installed legacy fat SessionStart hook to the thin shim.

    Idempotent, fail-soft, and **non-installing**: only touches the hook if it
    ALREADY exists and is not yet the shim — users who never installed the hook
    are left alone. Once migrated, the shim never goes stale (all logic is
    CLI-side), so this is a one-time transition. Returns True if it rewrote.
    """
    hook = home / ".claude" / "hooks" / "brainpalace-sessionstart.sh"
    try:
        if not hook.exists():
            return False
        current = hook.read_text(encoding="utf-8")
        if _SHIM_MARKER in current:
            return False  # already the shim
        shim = (
            files("brainpalace_cli.data.hooks")
            .joinpath("sessionstart-hook.sh")
            .read_text(encoding="utf-8")
        )
        hook.write_text(shim, encoding="utf-8")
        hook.chmod(0o755)
        return True
    except OSError:
        return False


def merge_hook_settings(
    settings: dict[str, Any], hooks: dict[str, str]
) -> dict[str, Any]:
    """Merge ``{event: command}`` into a Claude Code settings dict.

    Idempotent + non-destructive: preserves existing user hooks and skips any
    event whose script basename is already registered. Does not mutate the
    input ``settings``.
    """
    merged = copy.deepcopy(settings)
    hooks_root = merged.setdefault("hooks", {})

    for event, command in hooks.items():
        marker = _script_marker(command)
        groups = hooks_root.setdefault(event, [])
        already = any(
            marker in entry.get("command", "")
            for group in groups
            for entry in group.get("hooks", [])
        )
        if already:
            continue
        groups.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "timeout": TIMEOUTS.get(event, 5),
                    }
                ]
            }
        )
    return merged


def prune_cli_session_hooks(settings: dict[str, Any]) -> dict[str, Any]:
    """Remove the CLI-installed SessionStart shim(s) from a settings dict.

    Used when the Claude Code plugin is installed: the plugin provides
    SessionStart via ``plugin.json``, so a CLI-installed shim would inject the
    same guidance twice. Matches by script basename; preserves all other hooks.
    """
    merged = copy.deepcopy(settings)
    markers = set(_EVENT_SCRIPTS.values())
    for event, groups in list(merged.get("hooks", {}).items()):
        kept = []
        for g in groups:
            hs = [
                h
                for h in g.get("hooks", [])
                if not any(m in h.get("command", "") for m in markers)
            ]
            if hs:
                kept.append({**g, "hooks": hs})
        merged["hooks"][event] = kept
    return merged


def install_session_hooks(home: Path) -> dict[str, Any]:
    """Reconcile BrainPalace's Claude Code hooks in ``settings.json``.

    Plugin-aware to avoid a double-install: the Claude Code plugin already
    provides SessionStart (+ extraction) via ``plugin.json``. So when the plugin
    is installed this writes **no** SessionStart shim and removes any CLI shim a
    prior version left (self-healing the duplicate guidance injection). With no
    plugin, it writes the SessionStart reminder shim as before. Always prunes old
    plugin-owned extraction hooks. Backs up an existing ``settings.json``.
    """
    plugin = claude_plugin_installed(home)
    if not plugin:
        write_hook_scripts(home)

    hooks_dir = home / ".claude" / "hooks"
    commands = {
        event: f"bash {hooks_dir / script}" for event, script in _EVENT_SCRIPTS.items()
    }

    settings_path = home / ".claude" / "settings.json"
    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        settings_path.replace(settings_path.with_suffix(".json.bak"))

    existing = prune_extraction_hooks(existing)
    if plugin:
        # Plugin owns SessionStart — drop any CLI shim instead of adding one.
        merged = prune_cli_session_hooks(existing)
    else:
        merged = merge_hook_settings(existing, commands)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return merged


@click.command("install-session-hooks")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def install_session_hooks_command(json_output: bool) -> None:
    """Install BrainPalace's Claude Code SessionStart reminder hook into
    ``~/.claude/`` (and prune any old plugin-owned extraction hooks). The
    extraction hooks themselves now ship with the Claude Code plugin."""
    home = Path.home()
    install_session_hooks(home)
    plugin = claude_plugin_installed(home)
    scripts = sorted(_EVENT_SCRIPTS.values())
    if json_output:
        click.echo(
            json.dumps(
                {
                    "status": "skipped_plugin" if plugin else "installed",
                    "home": str(home),
                    "events": [] if plugin else sorted(_EVENT_SCRIPTS),
                    "scripts": [] if plugin else scripts,
                    "note": (
                        "plugin provides SessionStart; CLI shim not installed "
                        "(removed any duplicate)"
                        if plugin
                        else "SessionStart reminder only; "
                        "extraction hooks are plugin-owned"
                    ),
                },
                indent=2,
            )
        )
    elif plugin:
        click.echo(
            "BrainPalace plugin is installed — it provides SessionStart, so no "
            "CLI hook was added (any duplicate was removed)."
        )
    else:
        click.echo(f"Installed SessionStart reminder hook into {home / '.claude'}:")
        for event in sorted(_EVENT_SCRIPTS):
            click.echo(f"  • {event} → {_EVENT_SCRIPTS[event]}")
