"""whoami command — report the project and server that own a location."""

import json
from pathlib import Path

import click
from rich.console import Console

from brainpalace_cli.discovery import discover_project_dir, discover_server_url

console = Console()


@click.command("whoami")
@click.option(
    "--file",
    "file_path",
    type=click.Path(),
    default=None,
    help="Resolve ownership for this file/path instead of the current directory",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def whoami_command(file_path: str | None, json_output: bool) -> None:
    """Show which BrainPalace project and server own the current directory.

    Walks up from the current directory (or the ``--file`` path) to the owning
    project's ``.brainpalace/`` directory, then reports the project root and
    its running server.

    \b
    Exit codes:
      0  project found with a live server
      1  no project found
      2  project found but the server is not running
    """
    start: Path | None = None
    if file_path:
        start = Path(file_path).resolve()
        if start.is_file():
            start = start.parent

    project = discover_project_dir(start)
    if project is None:
        if json_output:
            click.echo(
                json.dumps(
                    {"found": False, "project_root": None, "url": None}, indent=2
                )
            )
        else:
            console.print("[yellow]No BrainPalace project found for this location.[/]")
        raise SystemExit(1)

    url = discover_server_url(start)
    if json_output:
        click.echo(
            json.dumps(
                {
                    "found": True,
                    "project_root": str(project),
                    "url": url,
                    "server": "running" if url else "down",
                },
                indent=2,
            )
        )
    else:
        console.print(f"[bold]Project:[/] {project}")
        if url:
            console.print(f"[bold]Server:[/]  {url} [green](running)[/]")
        else:
            console.print("[bold]Server:[/]  [red]not running[/]")

    raise SystemExit(0 if url else 2)
