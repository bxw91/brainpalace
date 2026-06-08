"""``brainpalace dashboard`` — launch/stop/inspect the control-plane dashboard.

The dashboard is a standalone web control plane that manages every BrainPalace
project server. It runs as its own process (port 8787, scanning upward) with a
dedicated runtime pidfile, separate from per-project servers.

The dashboard package (``brainpalace-dashboard``) is imported lazily so the CLI
keeps working when it isn't installed; a friendly install hint is printed on
ImportError.
"""

from __future__ import annotations

import json as _json
from typing import Any

import click
from rich.console import Console

console = Console()

_INSTALL_HINT = (
    "The dashboard package is not installed.\n"
    "It ships with the CLI automatically on Python 3.12+, so this usually means "
    "you're on Python 3.10/3.11.\n"
    "On Python 3.12+ install it with:\n"
    "  pip install brainpalace-dashboard\n"
    "(or, in a source checkout: cd brainpalace-dashboard && poetry install)"
)


def _load_dashboard_server() -> Any:
    """Import ``brainpalace_dashboard.server`` lazily.

    Raises:
        click.ClickException: With a friendly install hint when the dashboard
            package isn't importable.
    """
    try:
        from brainpalace_dashboard import server  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised via CLI test
        raise click.ClickException(_INSTALL_HINT) from exc
    return server


@click.group(name="dashboard")
def dashboard_command() -> None:
    """Manage the BrainPalace control-plane web dashboard.

    \b
    Subcommands:
      start    Launch the dashboard (scans port 8787->8887) and open a browser
      stop     Stop the running dashboard process
      status   Show whether the dashboard is running and healthy
    """


@dashboard_command.command(name="start")
@click.option("--host", default=None, help="Bind host (overrides config).")
@click.option("--port", type=int, default=None, help="Preferred port (scans upward).")
@click.option(
    "--foreground",
    "-f",
    is_flag=True,
    default=False,
    help="Run in the foreground (blocks; no browser opened).",
)
@click.option(
    "--no-open",
    is_flag=True,
    default=False,
    help="Do not open a browser after starting.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def start(
    host: str | None,
    port: int | None,
    foreground: bool,
    no_open: bool,
    as_json: bool,
) -> None:
    """Launch the dashboard and (unless --no-open/--foreground) open a browser."""
    server = _load_dashboard_server()
    try:
        url = server.launch_dashboard(
            host=host,
            port=port,
            open_browser=not (no_open or foreground),
            foreground=foreground,
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    if foreground:
        # launch_dashboard blocks in foreground mode; we only get here on exit.
        return

    if as_json:
        click.echo(_json.dumps({"status": "started", "base_url": url}))
        return

    from brainpalace_cli.commands._dashboard_url import render_dashboard_url

    render_dashboard_url({"base_url": url, "started": True}, console=console)
    console.print("[dim]Stop: brainpalace dashboard stop[/]")


@dashboard_command.command(name="stop")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def stop(as_json: bool) -> None:
    """Stop the running dashboard process."""
    server = _load_dashboard_server()
    result = server.stop_dashboard()

    if as_json:
        click.echo(_json.dumps(result))
        return

    if result.get("status") == "stopped":
        pid = result.get("pid")
        console.print(f"[green]Dashboard stopped[/] (pid {pid}).")
    else:
        console.print("[yellow]Dashboard is not running.[/]")


@dashboard_command.command(name="status")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def status(as_json: bool) -> None:
    """Show whether the dashboard is running and healthy."""
    server = _load_dashboard_server()
    result = server.dashboard_status()

    if as_json:
        click.echo(_json.dumps(result))
        return

    if result.get("status") == "running":
        healthy = result.get("healthy")
        health_str = "healthy" if healthy else "unhealthy"
        console.print("[bold green]Dashboard running[/]")
        console.print(f"URL: {result.get('base_url')}")
        console.print(f"PID: {result.get('pid')}")
        console.print(f"Port: {result.get('port')}")
        console.print(f"Health: {health_str}")
    else:
        console.print("[yellow]Dashboard is not running.[/]")
