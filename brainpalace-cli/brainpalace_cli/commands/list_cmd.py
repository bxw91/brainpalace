"""List command for showing all running BrainPalace instances."""

import json
import os
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from brainpalace_cli.runtime_probe import check_health as check_health  # re-export
from brainpalace_cli.runtime_probe import probe
from brainpalace_cli.xdg_paths import get_registry_path, get_xdg_state_dir

console = Console()

RUNTIME_FILE = "runtime.json"


def read_runtime(state_dir: Path) -> dict[str, Any] | None:
    """Read runtime state from state directory."""
    runtime_path = state_dir / RUNTIME_FILE
    if not runtime_path.exists():
        return None
    try:
        result: dict[str, Any] = json.loads(runtime_path.read_text())
        return result
    except Exception:
        return None


def is_process_alive(pid: int) -> bool:
    """Check if a process is alive."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it


def get_registry() -> dict[str, Any]:
    """Load the global registry of BrainPalace projects."""
    registry_path = get_registry_path()
    if not registry_path.exists():
        return {}
    try:
        result: dict[str, Any] = json.loads(registry_path.read_text())
        return result
    except Exception:
        return {}


def save_registry(registry: dict[str, Any]) -> None:
    """Save the global registry."""
    registry_dir = get_xdg_state_dir()
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry_path = registry_dir / "registry.json"
    registry_path.write_text(json.dumps(registry, indent=2))


def scan_instances() -> list[dict[str, Any]]:
    """Scan registry for running instances and validate them.

    Returns:
        List of instance info dictionaries with validation status.
    """
    registry = get_registry()
    instances = []
    stale_entries = []

    for project_root, entry in registry.items():
        state_dir = Path(entry.get("state_dir", ""))
        if not state_dir.exists():
            stale_entries.append(project_root)
            continue

        runtime = read_runtime(state_dir)
        if not runtime:
            stale_entries.append(project_root)
            continue

        pid = runtime.get("pid", 0)
        base_url = runtime.get("base_url", "")
        mode = runtime.get("mode", "project")
        started_at = runtime.get("started_at", "")

        # Validate process
        process_alive = is_process_alive(pid) if pid else False

        # Identity-checked health (A3): a bare 200 isn't proof this project's
        # server answered — a copied .brainpalace/'s runtime.json can point at
        # a DIFFERENT project's live server. probe() distinguishes "mine" from
        # "someone else answered" from "nobody answered".
        identity = probe(base_url, project_root) if base_url else "down"

        # Determine status
        if identity == "mine":
            status = "running"
        elif identity == "other":
            # A different project's server answered here — this entry is
            # simply not running (not "unhealthy", which would wrongly imply
            # THIS server is sick), and its registry entry is still valid for
            # a project that just isn't up yet — don't prune it.
            continue
        elif process_alive:
            status = "unhealthy"
        else:
            status = "stale"
            stale_entries.append(project_root)

        instances.append(
            {
                "project_root": project_root,
                "project_name": entry.get("project_name", Path(project_root).name),
                "base_url": base_url,
                "pid": pid,
                "mode": mode,
                "status": status,
                "started_at": started_at,
            }
        )

    # Clean up stale entries
    if stale_entries:
        for project_root in stale_entries:
            if project_root in registry:
                del registry[project_root]
        save_registry(registry)

    return instances


@click.command("list")
@click.option(
    "--all",
    "-a",
    "show_all",
    is_flag=True,
    help="Show all instances including stale ones",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def list_command(show_all: bool, json_output: bool) -> None:
    """List all running BrainPalace instances.

    Scans the global registry for BrainPalace instances and validates
    each one by checking if the process is alive and the health
    endpoint responds.

    \b
    Examples:
      brainpalace list            # List running instances
      brainpalace list --all      # Include stale instances
      brainpalace list --json     # Output as JSON
    """
    try:
        instances = scan_instances()

        # Filter unless --all
        if not show_all:
            instances = [i for i in instances if i["status"] == "running"]

        if json_output:
            click.echo(
                json.dumps(
                    {
                        "instances": instances,
                        "total": len(instances),
                    },
                    indent=2,
                )
            )
            return

        if not instances:
            console.print("[dim]No running BrainPalace instances found.[/]")
            console.print("\n[dim]Start a server with: brainpalace start[/]")
            return

        # Create table
        table = Table(
            title="BrainPalace Instances",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Project", style="bold")
        table.add_column("URL")
        table.add_column("PID", justify="right")
        table.add_column("Mode")
        table.add_column("Status")

        for instance in instances:
            # Color status
            status = instance["status"]
            if status == "running":
                status_text = "[green]running[/]"
            elif status == "unhealthy":
                status_text = "[yellow]unhealthy[/]"
            else:
                status_text = "[red]stale[/]"

            table.add_row(
                instance["project_name"],
                instance["base_url"],
                str(instance["pid"]) if instance["pid"] else "-",
                instance["mode"],
                status_text,
            )

        console.print(table)

        # Summary
        running_count = sum(1 for i in instances if i["status"] == "running")
        if running_count < len(instances):
            stale_count = len(instances) - running_count
            console.print(
                f"\n[dim]{running_count} running, {stale_count} stale/unhealthy[/]"
            )

    except PermissionError as e:
        if json_output:
            click.echo(json.dumps({"error": f"Permission denied: {e}"}))
        else:
            console.print(f"[red]Permission Error:[/] {e}")
        raise SystemExit(1) from e
    except OSError as e:
        if json_output:
            click.echo(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error:[/] {e}")
        raise SystemExit(1) from e
