"""Folders command group for managing indexed folders."""

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..client import (
    ConnectionError,
    DocServeClient,
    ServerError,
    exit_on_connection_error,
)
from ..config import get_server_url, get_state_dir
from .bm25_project import set_project_bm25

console = Console()


@click.group("folders")
def folders_group() -> None:
    """Manage indexed folders. List, add, or remove indexed folders.

    \b
    Examples:
      brainpalace folders list              # Show all indexed folders
      brainpalace folders add ./docs        # Index a new folder
      brainpalace folders remove ./docs     # Remove folder chunks
    """
    pass


@folders_group.command("list")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def list_folders_cmd(url: str | None, json_output: bool) -> None:
    """List all indexed folders with chunk counts and last indexed time.

    \b
    Examples:
      brainpalace folders list
      brainpalace folders list --json
    """
    resolved_url = url or get_server_url()

    try:
        with DocServeClient(base_url=resolved_url) as client:
            folders = client.list_folders()

            if json_output:
                output = {
                    "folders": [
                        {
                            "folder_path": f.folder_path,
                            "chunk_count": f.chunk_count,
                            "last_indexed": f.last_indexed,
                            "watch_mode": f.watch_mode,
                            "watch_debounce_seconds": f.watch_debounce_seconds,
                        }
                        for f in folders
                    ]
                }
                click.echo(json.dumps(output, indent=2))
                return

            if not folders:
                console.print("[dim]No folders indexed yet.[/]")
                return

            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Folder Path", style="bold")
            table.add_column("Chunks", justify="right")
            table.add_column("Last Indexed")
            table.add_column("Watch")

            for folder in folders:
                last_indexed = folder.last_indexed
                # Truncate microseconds for readability
                if "." in last_indexed:
                    last_indexed = last_indexed.split(".")[0]

                # Style watch_mode
                watch_display = folder.watch_mode
                if watch_display == "auto":
                    watch_display = "[cyan]auto[/cyan]"
                else:
                    watch_display = "[dim]off[/dim]"

                table.add_row(
                    folder.folder_path,
                    str(folder.chunk_count),
                    last_indexed,
                    watch_display,
                )

            console.print(table)

    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)

    except ServerError as e:
        if json_output:
            click.echo(json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e


@folders_group.command("add")
@click.argument("folder_path", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option(
    "--include-code/--no-code",
    "include_code",
    default=True,
    help=(
        "Index source code files alongside documents (default: ON). "
        "Use --no-code for doc-only repos."
    ),
)
@click.option(
    "--watch",
    "watch_mode",
    type=click.Choice(["off", "auto"], case_sensitive=False),
    default="auto",
    help="Watch mode: 'auto' enables file watching, 'off' disables (default: auto)",
)
@click.option(
    "--debounce",
    "debounce_seconds",
    type=int,
    default=None,
    help="Debounce interval in seconds for file watching (default: 30)",
)
@click.option(
    "--language",
    "text_language",
    default=None,
    help=(
        "Set the project default BM25 language (ISO 639-1) used to tokenize indexed "
        "folders (e.g. en, de, hr). Written to bm25.language in "
        ".brainpalace/config.yaml. "
        "No per-folder language isolation yet — this sets the project default."
    ),
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def add_folder_cmd(
    folder_path: str,
    url: str | None,
    include_code: bool,
    watch_mode: str | None,
    debounce_seconds: int | None,
    text_language: str | None,
    json_output: bool,
) -> None:
    """Index documents from a folder (alias for 'brainpalace index').

    FOLDER_PATH: Path to the folder containing documents to index.

    \b
    Examples:
      brainpalace folders add ./docs
      brainpalace folders add ./src --include-code
      brainpalace folders add ./src --watch auto --debounce 10
      brainpalace folders add ./docs --language hr
    """
    resolved_url = url or get_server_url()
    folder = Path(folder_path).resolve()

    # Persist --language into project config BEFORE sending the index request.
    if text_language is not None:
        state_dir = get_state_dir()
        set_project_bm25(state_dir, language=text_language)

    try:
        with DocServeClient(base_url=resolved_url) as client:
            response = client.index(
                folder_path=str(folder),
                include_code=include_code,
                watch_mode=watch_mode,
                watch_debounce_seconds=debounce_seconds,
            )

            if json_output:
                output = {
                    "job_id": response.job_id,
                    "status": response.status,
                    "message": response.message,
                    "folder": str(folder),
                }
                click.echo(json.dumps(output, indent=2))
                return

            console.print("\n[green]Indexing job queued![/]\n")
            console.print(f"[bold]Job ID:[/] {response.job_id}")
            console.print(f"[bold]Folder:[/] {folder}")
            console.print(f"[bold]Status:[/] {response.status}")
            if response.message:
                console.print(f"[bold]Message:[/] {response.message}")

            console.print("\n[dim]Use 'brainpalace jobs' to monitor progress.[/]")

    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)

    except ServerError as e:
        if json_output:
            click.echo(json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e


@folders_group.command("remove")
@click.argument("folder_path", type=str)
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
def remove_folder_cmd(
    folder_path: str,
    url: str | None,
    yes: bool,
    json_output: bool,
) -> None:
    """Remove all indexed chunks for a folder.

    FOLDER_PATH: Path to the indexed folder to remove.
    The folder does not need to exist on disk.

    \b
    Examples:
      brainpalace folders remove ./docs --yes
      brainpalace folders remove /absolute/path/to/docs
    """
    resolved_url = url or get_server_url()
    resolved_path = str(Path(folder_path).resolve())

    if not yes:
        click.confirm(
            f"Remove all indexed chunks for {resolved_path}?",
            abort=True,
        )

    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = client.delete_folder(folder_path=resolved_path)

            chunks_deleted = result.get("chunks_deleted", 0)
            message = result.get("message", "")

            if json_output:
                click.echo(json.dumps(result, indent=2))
                return

            console.print(
                f"\n[green]Removed {chunks_deleted} chunks for " f"{resolved_path}[/]"
            )
            if message:
                console.print(f"[dim]{message}[/]")

    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)

    except ServerError as e:
        if json_output:
            click.echo(json.dumps({"error": str(e), "detail": e.detail}))
        else:
            if e.status_code == 404:
                console.print(
                    f"[yellow]Folder not found:[/] {resolved_path} is not indexed"
                )
            elif e.status_code == 409:
                console.print(
                    "[red]Conflict:[/] An active indexing job is running "
                    "for this folder. Cancel the job first."
                )
            else:
                console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e


@folders_group.command("prune")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--dry-run",
    is_flag=True,
    help="List folders that would be pruned without deleting them.",
)
def prune_folders_cmd(url: str | None, json_output: bool, dry_run: bool) -> None:
    """Remove indexed-folder records whose path no longer exists on disk.

    Queries the server for all known folder records, checks each path
    locally, and removes any that are no longer present.

    \b
    Examples:
      brainpalace folders prune
      brainpalace folders prune --json
      brainpalace folders prune --dry-run
    """
    resolved_url = url or get_server_url()

    try:
        with DocServeClient(base_url=resolved_url) as client:
            records = client.list_folders()
            removed: list[str] = []
            errors: list[str] = []
            for rec in records:
                if not Path(rec.folder_path).exists():
                    if dry_run:
                        removed.append(rec.folder_path)
                    else:
                        try:
                            client.delete_folder(rec.folder_path)
                            removed.append(rec.folder_path)
                        except ServerError as e:
                            errors.append(
                                f"{rec.folder_path}: {getattr(e, 'detail', e)}"
                            )

        if dry_run:
            if json_output:
                click.echo(json.dumps({"would_prune": removed}, indent=2))
                return
            if removed:
                console.print(
                    f"[green]Would prune {len(removed)} dead folder record(s):[/]"
                )
                for p in removed:
                    console.print(f"  • {p}")
            else:
                console.print("[dim]No dead folder records found.[/]")
            return

        if json_output:
            output: dict[str, object] = {"pruned": removed}
            if errors:
                output["errors"] = errors
            click.echo(json.dumps(output, indent=2))
            return

        if removed:
            console.print(f"[green]Pruned {len(removed)} dead folder record(s):[/]")
            for p in removed:
                console.print(f"  • {p}")
        else:
            console.print("[dim]No dead folder records found.[/]")

        if errors:
            for err in errors:
                console.print(f"[red]Error:[/] {err}")

    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
