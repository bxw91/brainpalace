"""`brainpalace rehome` — show or resume the project-move rehome quarantine."""

import json
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

from ..client import (
    ConnectionError,
    DocServeClient,
    ServerError,
    exit_on_connection_error,
)
from ..config import get_server_url

console = Console()


def _render(data: dict[str, Any]) -> None:
    quarantined = bool(data.get("quarantined"))
    status = data.get("status")
    reason = data.get("reason") or data.get("note")
    if quarantined:
        body = (
            f"[bold red]QUARANTINED[/] (status: {status or 'pending'})\n"
            f"{reason or 'a project move needs rehoming'}\n\n"
            "The server serves only health + rehome until this completes.\n"
            "Run [bold]brainpalace rehome --resume[/] (or restart the server)."
        )
        console.print(Panel(body, title="Rehome", border_style="red"))
        return
    workers = data.get("resumed_workers")
    tail = f"\nResumed: {', '.join(workers)}" if workers else ""
    status_txt = f" (status: {status})" if status else ""
    body = (
        f"[green]No rehome pending[/]{status_txt} — the server is operating "
        f"normally.{tail}"
    )
    if reason:
        body += f"\n{reason}"
    console.print(Panel(body, title="Rehome", border_style="green"))


@click.command("rehome")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config)",
)
@click.option(
    "--resume", is_flag=True, help="Resume a pending/failed rehome from its checkpoint"
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def rehome_command(url: str | None, resume: bool, json_output: bool) -> None:
    """Show, or resume, the project-move rehome quarantine.

    A moved project auto-rehomes on server start; if it is mid-run or failed the
    server is fail-closed (503 on normal routes). This reports that state and can
    resume it. The durable path is a server restart (it auto-resumes on boot);
    ``--resume`` unblocks a running server in place.
    """
    resolved = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved) as client:
            data = client.rehome_resume() if resume else client.rehome_status()
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved, json_output=json_output)
        return
    except ServerError as e:
        # POST /rehome/resume returns 409 when there is nothing pending — that is a
        # normal answer ("not quarantined"), not a CLI failure.
        if resume and e.status_code == 409:
            data = {
                "quarantined": False,
                "status": None,
                "note": e.detail or "no pending rehome",
            }
        else:
            if json_output:
                click.echo(json.dumps({"error": str(e), "detail": e.detail}))
            else:
                console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
            raise SystemExit(1) from e

    if json_output:
        click.echo(json.dumps(data, indent=2))
        return
    _render(data)
