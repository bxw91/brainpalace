"""Uninstall command for removing all global BrainPalace data."""

import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.prompt import Confirm

from brainpalace_cli.commands.install_agent import INSTALL_DIRS
from brainpalace_cli.commands.update import detect_install_manager
from brainpalace_cli.xdg_paths import (
    LEGACY_DIR,
    get_registry_path,
    get_xdg_config_dir,
    get_xdg_state_dir,
)

console = Console()

# MCP client configs that may carry a `brainpalace` server entry, as
# (relative path, format, container key). The container holds named servers.
MCP_CONFIGS: list[tuple[str, str, str]] = [
    (".vscode/mcp.json", "json", "servers"),
    (".cursor/mcp.json", "json", "mcpServers"),
    (".cline/mcp.json", "json", "mcpServers"),
    (".zed/settings.json", "json", "context_servers"),
    (".continue/mcp.yaml", "yaml", "mcpServers"),
]


def parse_selection(sel: str, count: int) -> list[int]:
    """Parse a multi-select string into deduped, in-range 0-based indices.

    Accepts space/comma-separated numbers, ``N-M`` ranges, or ``all``.
    Out-of-range numbers and non-numeric tokens are dropped.
    """
    sel = sel.strip().lower()
    if sel == "all":
        return list(range(count))
    out: list[int] = []
    for tok in sel.replace(",", " ").split():
        nums: list[int] = []
        if "-" in tok:
            lo, _, hi = tok.partition("-")
            if lo.isdigit() and hi.isdigit():
                nums = list(range(int(lo), int(hi) + 1))
        elif tok.isdigit():
            nums = [int(tok)]
        for n in nums:
            idx = n - 1
            if 0 <= idx < count and idx not in out:
                out.append(idx)
    return out


def discover_plugin_dirs(projects: list[Path], home: Path | None = None) -> list[Path]:
    """Return existing plugin install dirs across runtimes + scopes.

    Global dirs come from ``INSTALL_DIRS[...]["global"]`` (``~`` expanded
    against ``home``); project dirs from the ``"project"`` template under each
    project root.
    """
    home = home or Path.home()
    candidates: list[Path] = []
    for spec in INSTALL_DIRS.values():
        gl = spec.get("global")
        if gl:
            candidates.append(Path(gl.replace("~", str(home), 1)))
        rel = spec.get("project")
        if rel:
            candidates.extend(proj / rel for proj in projects)
    return [d for d in candidates if d.is_dir()]


def discover_cc_marketplace_plugin(home: Path | None = None) -> list[Path]:
    """Return brainpalace plugin dirs installed via the Claude Code marketplace.

    These live under ``~/.claude/plugins/cache/<marketplace>/brainpalace`` and are
    tracked in Claude Code's own registry (``installed_plugins.json``). They are
    NOT removed here: deleting the cache by hand desyncs that registry, so the
    user must uninstall via Claude Code's ``/plugin`` manager instead.
    """
    home = home or Path.home()
    cache = home / ".claude" / "plugins" / "cache"
    if not cache.is_dir():
        return []
    return sorted(p for p in cache.glob("*/brainpalace") if p.is_dir())


def discover_mcp_configs(bases: list[Path]) -> list[tuple[Path, str, str]]:
    """Return existing MCP config files under each base as (path, fmt, key)."""
    found: list[tuple[Path, str, str]] = []
    for base in bases:
        for rel, fmt, key in MCP_CONFIGS:
            p = base / rel
            if p.is_file():
                found.append((p, fmt, key))
    return found


def remove_mcp_entry(path: Path, fmt: str, key: str) -> bool:
    """Remove the ``brainpalace`` server entry from one MCP config.

    Backs the file up (``<name>.bak.<ts>``) before writing. Returns True if an
    entry was removed, False if there was nothing to do or the file was
    unparseable.
    """
    try:
        if fmt == "yaml":
            import yaml

            data = yaml.safe_load(path.read_text()) or {}
        else:
            data = json.loads(path.read_text())
    except Exception:
        return False

    if not isinstance(data, dict):
        return False
    container = data.get(key)
    changed = False
    if isinstance(container, dict) and "brainpalace" in container:
        del container["brainpalace"]
        changed = True
    elif isinstance(container, list):
        kept = [
            x
            for x in container
            if not (isinstance(x, dict) and x.get("name") == "brainpalace")
        ]
        if len(kept) != len(container):
            data[key] = kept
            changed = True

    if not changed:
        return False

    backup = path.with_name(f"{path.name}.bak.{int(time.time())}")
    backup.write_text(path.read_text())
    if fmt == "yaml":
        import yaml

        path.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False))
    else:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return True


def package_uninstall_plan(manager: str | None) -> tuple[str, list[str]]:
    """Map an install manager to a (mode, argv) package-removal plan.

    ``exec`` = safe to run as the final act (pipx/uv run from their own venv);
    ``manual`` = print the command for the user (can't remove the running
    interpreter's own env); ``unknown`` = no plan.
    """
    if manager == "pipx":
        return "exec", ["pipx", "uninstall", "brainpalace-cli"]
    if manager == "uv":
        return "exec", ["uv", "tool", "uninstall", "brainpalace-cli"]
    if manager == "pip":
        return "manual", [
            sys.executable,
            "-m",
            "pip",
            "uninstall",
            "brainpalace-rag",
            "brainpalace-cli",
            "-y",
        ]
    return "unknown", []


def remaining_steps_message(manager: str | None, mode: str, argv: list[str]) -> str:
    """Human-readable list of manual steps left after the guided teardown."""
    lines = ["Remaining steps (manual):"]
    if mode == "manual" and argv:
        lines.append(
            "  - finish removing the package (can't self-delete the running env):"
        )
        lines.append(f"      {' '.join(argv)}")
        lines.append(
            "      (if that fails with 'externally-managed-environment' on a "
            "Debian/Ubuntu system Python, re-run it with --break-system-packages)"
        )
    elif mode == "unknown":
        lines.append(
            "  - uninstall the package with your installer "
            "(pipx/uv/pip uninstall brainpalace-cli)."
        )
    lines.append(
        "  - remove any `export <PROVIDER>_API_KEY=…` from your shell rc "
        "(only if it's not shared with other tools — your API key is left "
        "untouched)."
    )
    return "\n".join(lines)


def _read_registry(registry_path: Path) -> dict[str, Any]:
    """Read registry.json from given path.

    Args:
        registry_path: Path to registry.json file.

    Returns:
        Registry dict, or empty dict if file is missing or unreadable.
    """
    if not registry_path.exists():
        return {}
    try:
        result: dict[str, Any] = json.loads(registry_path.read_text())
        return result
    except Exception:
        return {}


def _read_runtime(state_dir: Path) -> dict[str, Any] | None:
    """Read runtime.json from state directory.

    Args:
        state_dir: Path to project state directory.

    Returns:
        Runtime dict or None if not found.
    """
    runtime_path = state_dir / "runtime.json"
    if not runtime_path.exists():
        return None
    try:
        result: dict[str, Any] = json.loads(runtime_path.read_text())
        return result
    except Exception:
        return None


def _stop_servers(registry: dict[str, Any]) -> int:
    """Send SIGTERM to all running server processes in registry.

    Args:
        registry: Registry dict with project entries.

    Returns:
        Count of servers that received SIGTERM.
    """
    stopped = 0
    for _project_root, entry in registry.items():
        state_dir = Path(entry.get("state_dir", ""))
        if not state_dir.exists():
            continue
        runtime = _read_runtime(state_dir)
        if not runtime:
            continue
        pid = runtime.get("pid")
        if not pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            stopped += 1
        except (ProcessLookupError, PermissionError):
            pass

    if stopped > 0:
        time.sleep(0.5)  # Brief wait for graceful shutdown

    return stopped


def _exec_package(argv: list[str]) -> None:
    """Replace the current process with the package-uninstall command.

    Used for pipx/uv, which run from their own venv, so removing the
    brainpalace-cli venv is safe. Does not return on success.
    """
    os.execvp(argv[0], argv)


def _guided_uninstall() -> None:
    """Interactive teardown: confirm each step, then print what's left."""
    console.print("[bold]Guided BrainPalace uninstall[/] — every step is confirmed.\n")
    registry = _read_registry(get_registry_path())
    projects = [Path(p) for p in registry]

    # 1. Stop servers.
    if registry:
        if Confirm.ask("Stop all running servers?", default=True):
            n = _stop_servers(registry)
            console.print(f"  [dim]stopped {n} server(s).[/]")

    # 2. Plugins (all runtimes, both scopes).
    plugin_dirs = discover_plugin_dirs(projects)
    if plugin_dirs:
        console.print("\nPlugin dirs found:")
        for d in plugin_dirs:
            console.print(f"  {d}")
        if Confirm.ask("Remove these plugin dirs?", default=True):
            for d in plugin_dirs:
                shutil.rmtree(d, ignore_errors=True)
            console.print("  [dim]plugins removed.[/]")

    # Claude Code marketplace plugin — managed by Claude Code's own registry, so
    # we advise (not delete): hand-removing the cache desyncs installed_plugins.json.
    cc_market = discover_cc_marketplace_plugin()
    if cc_market:
        console.print(
            "\n[yellow]Claude Code marketplace plugin detected[/] "
            "(managed by Claude Code — not removed here):"
        )
        for d in cc_market:
            console.print(f"  {d}")
        console.print(
            "  To remove it, in Claude Code run [bold]/plugin[/] → uninstall "
            '"brainpalace"\n'
            '  (and optionally remove the "brainpalace-marketplace").\n'
            "  [dim]Don't delete the cache dir by hand — it desyncs Claude Code's "
            "plugin registry.[/]"
        )

    # 3. MCP client configs (surgical — keeps other servers).
    mcp = discover_mcp_configs(projects + [Path.home()])
    if mcp:
        if Confirm.ask(
            "\nStrip the brainpalace entry from MCP configs (backs up first)?",
            default=True,
        ):
            for path, fmt, key in mcp:
                if remove_mcp_entry(path, fmt, key):
                    console.print(f"  [dim]cleaned {path}[/]")

    # 4. Per-project state (multi-select — ⚠️ archived transcripts).
    state_dirs: list[Path] = []
    for entry in registry.values():
        sd = Path(entry.get("state_dir", ""))
        if sd.is_dir():
            state_dirs.append(sd)
    if state_dirs:
        console.print(
            "\n[yellow]Per-project state[/] (⚠️ includes archived raw transcripts):"
        )
        for i, d in enumerate(state_dirs, 1):
            console.print(f"  {i}) {d}")
        sel = click.prompt(
            "Delete which? (numbers/ranges/all, blank = skip)",
            default="",
            show_default=False,
        )
        for idx in parse_selection(sel, len(state_dirs)):
            shutil.rmtree(state_dirs[idx], ignore_errors=True)
            console.print(f"  [dim]deleted {state_dirs[idx]}[/]")

    # 5. Global state.
    global_dirs = [
        d for d in (get_xdg_config_dir(), get_xdg_state_dir(), LEGACY_DIR) if d.exists()
    ]
    if global_dirs:
        console.print("\nGlobal state:")
        for d in global_dirs:
            console.print(f"  {d}")
        if Confirm.ask("Delete global state?", default=True):
            for d in global_dirs:
                shutil.rmtree(d, ignore_errors=True)
            console.print("  [dim]global state removed.[/]")

    # 6. Package removal + remaining manual steps.
    manager = detect_install_manager()
    mode, argv = package_uninstall_plan(manager)
    console.print()
    console.print(remaining_steps_message(manager, mode, argv))
    if mode == "exec" and argv:
        if Confirm.ask(
            f"\nRun `{' '.join(argv)}` now (replaces this process)?", default=True
        ):
            _exec_package(argv)  # does not return on success


@click.command("uninstall")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def uninstall_command(yes: bool, json_output: bool) -> None:
    """Uninstall BrainPalace.

    Run with no flags for a [bold]guided teardown[/] — confirms each step:
    stop servers, remove plugin dirs, strip MCP entries, delete per-project
    and global state, then print the leftover manual steps (the package
    uninstall for pip installs, and your shell-rc API key).

    With ``--yes`` / ``--json`` it stays non-interactive and removes only the
    global data (XDG + legacy dirs) and stops servers — it does NOT remove
    project-level ``.brainpalace/`` dirs.

    \b
    Examples:
      brainpalace uninstall           # Guided teardown (recommended)
      brainpalace uninstall --yes     # Non-interactive: global data only
      brainpalace uninstall --json    # Machine output: global data only
    """
    if not yes and not json_output:
        _guided_uninstall()
        return

    # Collect directories to remove (only existing ones)
    dirs_to_remove: list[Path] = []
    for d in [get_xdg_config_dir(), get_xdg_state_dir(), LEGACY_DIR]:
        if d.exists():
            dirs_to_remove.append(d)

    if not dirs_to_remove:
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "status": "nothing_to_remove",
                        "removed": [],
                        "servers_stopped": 0,
                    }
                )
            )
        else:
            console.print(
                "[dim]Nothing to remove. BrainPalace is not installed globally.[/]"
            )
        return

    # Prompt for confirmation unless --yes or --json
    if not yes and not json_output:
        console.print(
            "[yellow]Warning:[/] This will permanently remove all global "
            "BrainPalace data:\n"
        )
        for d in dirs_to_remove:
            console.print(f"  [red]✗[/] {d}")
        console.print()
        if not Confirm.ask("Remove all BrainPalace global data?", default=False):
            console.print("[dim]Aborted.[/]")
            return

    # Stop running servers before removing directories
    registry_path = get_registry_path()
    registry = _read_registry(registry_path)
    servers_stopped = _stop_servers(registry)

    # Remove directories
    removed: list[str] = []
    for d in dirs_to_remove:
        try:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(str(d))
        except OSError:
            pass

    # Report results
    if json_output:
        click.echo(
            json.dumps(
                {
                    "status": "uninstalled",
                    "removed": removed,
                    "servers_stopped": servers_stopped,
                },
                indent=2,
            )
        )
    else:
        console.print("\n[green]BrainPalace global data removed:[/]")
        for path in removed:
            console.print(f"  [dim]removed:[/] {path}")
        if servers_stopped > 0:
            console.print(f"\n[dim]Stopped {servers_stopped} running server(s).[/]")
