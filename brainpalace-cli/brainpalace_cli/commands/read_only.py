"""`brainpalace read-only on|off|status` — toggle the provider kill switch.

Writes the sparse ``server.read_only`` override into the project
``.brainpalace/config.yaml`` (``on``), or removes it so the key inherits
(``off``). ``status`` reports the effective value + source.

The server resolves the IDENTICAL keys — ``server.read_only`` config plus the
``BRAINPALACE_READ_ONLY`` env override (env wins) — via
``brainpalace_server.config.runtime_mode.is_read_only``. This command resolves
them locally (no server import) so it works regardless of the bundled server
version; the two MUST stay in sync (setup-surface parity).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console

from brainpalace_cli.commands.config import _find_config_file

console = Console()

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def _project_config_path() -> Path:
    found = _find_config_file()
    if found is not None:
        return Path(found)
    return Path.cwd() / ".brainpalace" / "config.yaml"


def _load(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            return {}
    return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _resolve_read_only(path: Path) -> tuple[bool, str]:
    """Effective read-only state + its source. Env wins over config."""
    env = os.getenv("BRAINPALACE_READ_ONLY")
    if env is not None:
        token = env.strip().lower()
        if token in _TRUE:
            return True, "BRAINPALACE_READ_ONLY env"
        if token in _FALSE:
            return False, "BRAINPALACE_READ_ONLY env"
    data = _load(path)
    server = data.get("server") if isinstance(data, dict) else None
    value = bool(server.get("read_only", False)) if isinstance(server, dict) else False
    return value, str(path)


@click.command("read-only")
@click.argument("action", type=click.Choice(["on", "off", "status"]))
def read_only_command(action: str) -> None:
    """Enable/disable read-only mode (disables embedding, summarization, writes)."""
    path = _project_config_path()

    if action == "on":
        data = _load(path)
        data.setdefault("server", {})["read_only"] = True
        _save(path, data)
        console.print("[green]Read-only mode ON[/] — provider calls + writes disabled.")
        console.print(
            "[dim]Restart the server to apply: brainpalace stop && brainpalace start[/]"
        )
        return

    if action == "off":
        data = _load(path)
        server = data.get("server")
        if isinstance(server, dict) and "read_only" in server:
            del server["read_only"]
            if not server:
                del data["server"]
            _save(path, data)
        console.print(
            "[green]Read-only mode OFF[/] — normal operation (after restart)."
        )
        return

    # status
    state, source = _resolve_read_only(path)
    label = "[red]ON[/]" if state else "[green]OFF[/]"
    console.print(f"Read-only mode: {label}")
    console.print(f"[dim]source: {source}[/]")
