"""Status command for checking server health."""

from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..client import (
    ConnectionError,
    DocServeClient,
    ServerError,
    exit_on_connection_error,
)
from ..config import get_server_url

console = Console()


def _status_all(json_output: bool) -> None:
    """Show detailed status for every running registered server (B2b)."""
    import json

    from .list_cmd import scan_instances

    instances = [i for i in scan_instances() if i.get("status") == "running"]
    servers: list[dict[str, Any]] = []
    for inst in instances:
        base_url = str(inst.get("base_url", ""))
        if not base_url:
            continue
        try:
            with DocServeClient(base_url=base_url) as client:
                health = client.health()
                indexing = client.status()
        except (ConnectionError, ServerError):
            continue  # Server vanished between registry scan and probe.
        watcher = indexing.file_watcher or {}
        servers.append(
            {
                "project_root": inst.get("project_root", ""),
                "base_url": base_url,
                "pid": inst.get("pid", 0),
                "health": health.status,
                "version": health.version,
                "total_documents": indexing.total_documents,
                "total_chunks": indexing.total_chunks,
                "watcher_running": bool(watcher.get("running", False)),
                "watched_folders": int(watcher.get("watched_folders", 0)),
                "last_indexed_at": indexing.last_indexed_at,
            }
        )

    if json_output:
        click.echo(json.dumps({"servers": servers, "total": len(servers)}, indent=2))
        return

    if not servers:
        console.print("[dim]No running BrainPalace servers found.[/]")
        console.print("\n[dim]Start a server with: brainpalace start[/]")
        return

    for srv in servers:
        if srv["watcher_running"]:
            watcher_txt = f"running ({srv['watched_folders']} folder(s))"
        else:
            watcher_txt = "stopped"
        last_indexed = srv["last_indexed_at"] or "never"
        body = (
            f"[bold]URL:[/] {srv['base_url']}\n"
            f"[bold]PID:[/] {srv['pid']}\n"
            f"[bold]Health:[/] {srv['health']}\n"
            f"[bold]Chunks:[/] {srv['total_chunks']:,} "
            f"({srv['total_documents']:,} documents)\n"
            f"[bold]Watcher:[/] {watcher_txt}\n"
            f"[bold]Last indexed:[/] {last_indexed}"
        )
        console.print(Panel(body, title=str(srv["project_root"]), border_style="cyan"))

    console.print(f"\n[dim]{len(servers)} running server(s).[/]")


@click.command("status")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show additional detail")
@click.option(
    "--all",
    "-a",
    "show_all",
    is_flag=True,
    help="Show detailed status for every running registered server",
)
def status_command(
    url: str | None, json_output: bool, verbose: bool, show_all: bool
) -> None:
    """Check BrainPalace server status and health."""
    if show_all:
        _status_all(json_output)
        return
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            health = client.health()
            indexing = client.status()

            if json_output:
                import json

                output = {
                    "health": {
                        "status": health.status,
                        "message": health.message,
                        "version": health.version,
                    },
                    "indexing": {
                        "total_documents": indexing.total_documents,
                        "total_chunks": indexing.total_chunks,
                        "indexing_in_progress": indexing.indexing_in_progress,
                        "progress_percent": indexing.progress_percent,
                        "indexed_folders": indexing.indexed_folders,
                        "file_watcher": indexing.file_watcher
                        or {"running": False, "watched_folders": 0},
                        "embedding_cache": indexing.embedding_cache,
                        "features": getattr(indexing, "features", None),
                    },
                }
                click.echo(json.dumps(output, indent=2))
                return

            # Determine status color
            status_color = {
                "healthy": "green",
                "indexing": "yellow",
                "degraded": "orange3",
                "unhealthy": "red",
            }.get(health.status, "white")

            # Create status panel
            status_text = f"[bold {status_color}]{health.status.upper()}[/]"
            if health.message:
                status_text += f"\n{health.message}"

            console.print(
                Panel(status_text, title="Server Status", border_style=status_color)
            )

            # Create info table
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Metric", style="dim")
            table.add_column("Value")

            table.add_row("Server Version", health.version)
            table.add_row("Total Documents", str(indexing.total_documents))
            table.add_row("Total Chunks", str(indexing.total_chunks))

            if indexing.indexing_in_progress:
                table.add_row(
                    "Indexing Progress", f"[yellow]{indexing.progress_percent:.1f}%[/]"
                )
                if indexing.current_job_id:
                    table.add_row("Current Job", indexing.current_job_id)
            else:
                table.add_row("Indexing", "[green]Idle[/]")

            if indexing.indexed_folders:
                table.add_row(
                    "Indexed Folders",
                    "\n".join(indexing.indexed_folders[:5])
                    + (
                        f"\n... and {len(indexing.indexed_folders) - 5} more"
                        if len(indexing.indexed_folders) > 5
                        else ""
                    ),
                )

            if indexing.last_indexed_at:
                table.add_row("Last Indexed", indexing.last_indexed_at)

            features = getattr(indexing, "features", None) or {}

            # File watcher — prefer the consolidated feature view (clearer
            # 0-folder state), fall back to the legacy top-level field.
            fw_feat = features.get("file_watcher")
            if isinstance(fw_feat, dict):
                enabled = bool(fw_feat.get("enabled"))
                watched = int(fw_feat.get("watched_folders", 0) or 0)
                if enabled and watched == 0:
                    table.add_row(
                        "File Watcher",
                        "running ([yellow]0 folders — none marked watch=auto[/])",
                    )
                elif enabled:
                    table.add_row(
                        "File Watcher", f"running ({watched} watched folder(s))"
                    )
                else:
                    table.add_row("File Watcher", "stopped")
            else:
                file_watcher = indexing.file_watcher or {}
                if file_watcher:
                    running = bool(file_watcher.get("running", False))
                    watched_folders = int(file_watcher.get("watched_folders", 0))
                    watcher_status = "running" if running else "stopped"
                    table.add_row(
                        "File Watcher",
                        f"{watcher_status} ({watched_folders} watched folder(s))",
                    )

            # Session archive (raw transcript backup) — independent of index.
            arch = features.get("session_archive")
            if isinstance(arch, dict):
                if arch.get("enabled"):
                    files = int(arch.get("archived_files", 0) or 0)
                    size_mb = int(arch.get("archived_bytes", 0) or 0) / (1024 * 1024)
                    retain = int(arch.get("retain_days", 0) or 0)
                    window = "forever" if retain <= 0 else f"{retain}d"
                    table.add_row(
                        "Session Archive",
                        f"[green]on[/] — {files:,} files, {size_mb:.1f} MB ({window})",
                    )
                else:
                    table.add_row(
                        "Session Archive",
                        "[dim]off[/] (SESSION_ARCHIVE_ENABLED=false)",
                    )

            # Session memory / INDEX (from the feature view).
            sess = features.get("session_memory")
            if isinstance(sess, dict):
                if sess.get("enabled"):
                    sess_state = "watching" if sess.get("watcher_running") else "idle"
                    table.add_row(
                        "Session Memory",
                        f"[green]on[/] ({sess_state}) — "
                        f"{int(sess.get('session_chunks', 0) or 0):,} session "
                        f"chunks, {int(sess.get('curated_memories', 0) or 0):,} "
                        f"curated",
                    )
                else:
                    table.add_row(
                        "Session Memory",
                        "[dim]off[/] (enable: brainpalace init --sessions)",
                    )

            # Show embedding cache status if available (Phase 16)
            embedding_cache = indexing.embedding_cache
            if embedding_cache:
                entry_count = int(embedding_cache.get("entry_count", 0))
                hit_rate = float(embedding_cache.get("hit_rate", 0.0))
                hits = int(embedding_cache.get("hits", 0))
                misses = int(embedding_cache.get("misses", 0))
                table.add_row(
                    "Embedding Cache",
                    f"{entry_count:,} entries, {hit_rate:.1%} hit rate "
                    f"({hits:,} hits, {misses:,} misses)",
                )
                if verbose:
                    mem_entries = int(embedding_cache.get("mem_entries", 0))
                    size_bytes = int(embedding_cache.get("size_bytes", 0))
                    size_mb = size_bytes / (1024 * 1024) if size_bytes else 0.0
                    table.add_row("  Memory Entries", f"{mem_entries:,}")
                    table.add_row("  Cache Size", f"{size_mb:.2f} MB")

            # Show graph index status if available (Feature 113)
            graph_status = getattr(indexing, "graph_index", None)
            if graph_status:
                if graph_status.get("enabled"):
                    entities = graph_status.get("entity_count", 0)
                    rels = graph_status.get("relationship_count", 0)
                    table.add_row(
                        "Graph Index",
                        f"[green]Enabled[/] - {entities} entities, {rels} rels",
                    )
                else:
                    table.add_row("Graph Index", "[dim]Disabled[/]")

            console.print(table)

    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)

    except ServerError as e:
        if json_output:
            import json

            click.echo(json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e
