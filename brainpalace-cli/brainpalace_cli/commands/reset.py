"""Reset command for clearing the index."""

import click
from rich.console import Console
from rich.prompt import Confirm

from ..client import (
    ConnectionError,
    DocServeClient,
    ServerError,
    exit_on_connection_error,
)
from ..config import get_server_url, get_state_dir

console = Console()


@click.command("reset")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--include-sessions",
    is_flag=True,
    default=False,
    help="Also delete the raw session archive (.brainpalace/session_archive). "
    "Off by default — the archive survives a normal reset.",
)
def reset_command(
    url: str | None, yes: bool, json_output: bool, include_sessions: bool
) -> None:
    """Reset the index by deleting all indexed documents.

    WARNING: This permanently removes all indexed content.
    """
    # Get URL from config if not specified
    resolved_url = url or get_server_url()

    # Confirm unless --yes flag provided
    if not yes and not json_output:
        console.print(
            "[yellow]Warning:[/] This will permanently delete all indexed documents."
        )
        if not Confirm.ask("Are you sure you want to reset the index?"):
            console.print("[dim]Aborted.[/]")
            return

    try:
        with DocServeClient(base_url=resolved_url) as client:
            response = client.reset()

            if json_output:
                import json

                output = {
                    "job_id": response.job_id,
                    "status": response.status,
                    "message": response.message,
                }
                if include_sessions:
                    import shutil

                    archive_dir = get_state_dir() / "session_archive"
                    if archive_dir.exists():
                        shutil.rmtree(archive_dir)
                click.echo(json.dumps(output, indent=2))
                return

            console.print("\n[green]Index reset successfully![/]")
            if response.message:
                console.print(f"[bold]Message:[/] {response.message}")

            if include_sessions:
                import shutil

                archive_dir = get_state_dir() / "session_archive"
                if archive_dir.exists():
                    shutil.rmtree(archive_dir)
                    console.print(f"[yellow]Deleted session archive:[/] {archive_dir}")
                else:
                    console.print("[dim]No session archive to delete.[/]")
            else:
                console.print(
                    "[dim]Session archive preserved "
                    "(use --include-sessions to delete it).[/]"
                )

    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)

    except ServerError as e:
        if json_output:
            import json

            click.echo(json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
            if e.status_code == 409:
                console.print(
                    "\n[dim]Cannot reset while indexing is in progress. "
                    "Wait for indexing to complete first.[/]"
                )
        raise SystemExit(1) from e
