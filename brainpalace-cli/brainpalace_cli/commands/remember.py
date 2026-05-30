"""`remember` command — add a curated memory (Phase 030)."""

import click
from rich.console import Console

from ..client import (
    ConnectionError,
    DocServeClient,
    ServerError,
    exit_on_connection_error,
)
from ..config import get_server_url

console = Console()


@click.command("remember")
@click.argument("text")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config)",
)
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--section", default="Notes", help="Markdown section to file under")
def remember_command(text: str, url: str | None, tags: str, section: str) -> None:
    """Save a curated fact to the project's memory (BRAINPALACE_MEMORY.md)."""
    resolved_url = url or get_server_url()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        with DocServeClient(base_url=resolved_url) as client:
            data = client.remember(text=text, section=section, tags=tag_list)
        mem = data.get("memory", {})
        console.print(
            f"[green]Saved[/green] memory [bold]{mem.get('id', '?')}[/bold] "
            f"in [cyan]{mem.get('section', section)}[/cyan]"
        )
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url)
    except ServerError as e:
        console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e
