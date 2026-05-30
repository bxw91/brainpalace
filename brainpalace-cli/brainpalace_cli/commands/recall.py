"""`recall` command — search the curated memory namespace only (Phase 030)."""

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


@click.command("recall")
@click.argument("query_text")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config)",
)
@click.option("-k", "--top-k", default=5, type=int, help="Number of memories to return")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def recall_command(
    query_text: str, url: str | None, top_k: int, json_output: bool
) -> None:
    """Recall curated memories matching a query (memory namespace only)."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            data = client.recall(query_text, top_k=top_k)
        if json_output:
            import json

            click.echo(json.dumps(data, indent=2))
            return
        hits = data.get("hits", [])
        if not hits:
            console.print("[yellow]No matching memories.[/]")
            return
        for i, h in enumerate(hits, 1):
            console.print(
                f"[cyan][{i}][/] [dim]({h.get('score', 0):.2f})[/] {h.get('text', '')}"
                + (f"  [dim]#{','.join(h.get('tags', []))}[/]" if h.get("tags") else "")
            )
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e
