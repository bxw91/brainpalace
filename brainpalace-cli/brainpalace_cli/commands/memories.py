"""`memories` command group — list/show/delete/obsolete curated memories."""

import click
from rich.console import Console
from rich.table import Table

from ..client import (
    ConnectionError,
    DocServeClient,
    ServerError,
    exit_on_connection_error,
)
from ..config import get_server_url

console = Console()


def _url(url: str | None) -> str:
    return url or get_server_url()


@click.group("memories")
def memories_group() -> None:
    """Manage the curated memory namespace (Phase 030)."""


_url_option = click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config)",
)


@memories_group.command("list")
@_url_option
@click.option("--tag", default=None, help="Filter by tag")
@click.option("--section", default=None, help="Filter by section")
@click.option("--all", "include_obsolete", is_flag=True, help="Include obsolete")
def list_memories(
    url: str | None, tag: str | None, section: str | None, include_obsolete: bool
) -> None:
    """List curated memories."""
    resolved = _url(url)
    try:
        with DocServeClient(base_url=resolved) as client:
            data = client.list_memories(
                tag=tag, section=section, include_obsolete=include_obsolete
            )
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved)
    except ServerError as e:
        console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e

    mems = data.get("memories", [])
    if not mems:
        console.print("[yellow]No memories.[/]")
        return
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("id")
    table.add_column("section")
    table.add_column("text")
    table.add_column("tags")
    for m in mems:
        flag = "" if m.get("obsoleted_at") is None else " [dim](obsolete)[/]"
        table.add_row(
            m.get("id", ""),
            m.get("section", ""),
            (m.get("text", "") + flag),
            ",".join(m.get("tags", [])),
        )
    console.print(table)
    console.print(
        f"[dim]{data.get('total', len(mems))} shown · "
        f"{data.get('char_count', 0)}/{data.get('char_cap', 0)} chars[/]"
    )


@memories_group.command("show")
@click.argument("memory_id")
@_url_option
def show_memory(memory_id: str, url: str | None) -> None:
    """Show one memory by id."""
    resolved = _url(url)
    try:
        with DocServeClient(base_url=resolved) as client:
            data = client.list_memories(include_obsolete=True)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved)
    except ServerError as e:
        console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e
    for m in data.get("memories", []):
        if m.get("id") == memory_id:
            console.print(m)
            return
    console.print(f"[red]No memory {memory_id}[/]")
    raise SystemExit(1)


@memories_group.command("delete")
@click.argument("memory_id")
@_url_option
def delete_memory(memory_id: str, url: str | None) -> None:
    """Delete a memory by id."""
    resolved = _url(url)
    try:
        with DocServeClient(base_url=resolved) as client:
            client.delete_memory(memory_id)
        console.print(f"[green]Deleted[/green] {memory_id}")
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved)
    except ServerError as e:
        console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e


@memories_group.command("obsolete")
@click.argument("memory_id")
@_url_option
@click.option("--superseded-by", default=None, help="Id of the replacing memory")
def obsolete_memory(memory_id: str, url: str | None, superseded_by: str | None) -> None:
    """Mark a memory obsolete (kept in the file, dropped from the index)."""
    resolved = _url(url)
    try:
        with DocServeClient(base_url=resolved) as client:
            client.obsolete_memory(memory_id, superseded_by=superseded_by)
        console.print(f"[green]Obsoleted[/green] {memory_id}")
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved)
    except ServerError as e:
        console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e
