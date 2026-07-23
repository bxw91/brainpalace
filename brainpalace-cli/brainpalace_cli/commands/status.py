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
from ._dashboard_url import dashboard_status_info, render_dashboard_status

console = Console()


def _load_bm25_config_for_status() -> dict[str, str]:
    """Load BM25 language/engine from the project config.yaml, if available.

    Returns a dict with 'language' and 'engine' keys, or an empty dict when
    no config.yaml is found (e.g. status run outside an initialized project).

    Kept ONLY for the `--json` output's back-compat `bm25` key (Global
    Constraint: existing `bp status --json` keys are unchanged). The
    human-readable BM25 row is no longer built from this — it comes from the
    server's shared status report (``report.rows`` key ``bm25_language``),
    same as every other row.
    """
    try:
        from brainpalace_server.config.bm25_config import load_bm25_config

        cfg = load_bm25_config()
        return {"language": cfg.language, "engine": cfg.engine}
    except Exception:  # noqa: BLE001
        return {}


# Tone -> Rich color name, matching brainpalace_server.status_report.Tone.
_TONE_RICH: dict[str, str | None] = {
    "default": None,
    "good": "green",
    "warn": "yellow",
    "bad": "red",
    "dim": "dim",
    "accent": "cyan",
}
# Alert severity -> Rich Panel border color.
_ALERT_BORDER = {"info": "cyan", "warn": "yellow", "bad": "red"}


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
    bm25_cfg = _load_bm25_config_for_status()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            health = client.health()
            indexing = client.status()

            if json_output:
                import json

                output: dict[str, Any] = {
                    "health": {
                        "status": health.status,
                        "message": health.message,
                        "version": health.version,
                        "url": resolved_url,
                    },
                    "dashboard": dashboard_status_info(),
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
                        "graph_index": getattr(indexing, "graph_index", None),
                        "index_warnings": indexing.index_warnings,
                    },
                    "report": getattr(indexing, "report", None),
                }
                if bm25_cfg:
                    output["bm25"] = bm25_cfg
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
            status_text += f"\n[bold]URL:[/] [link={resolved_url}]{resolved_url}[/link]"

            console.print(
                Panel(status_text, title="Server Status", border_style=status_color)
            )

            # Presentation-neutral status report — the single source both
            # `bp status` and the dashboard Status tab render (see
            # brainpalace_server.status_report). Add a row/alert there -> it
            # appears here and on the web automatically.
            report = getattr(indexing, "report", None) or {"rows": [], "alerts": []}

            for alert in report.get("alerts", []):
                severity = alert.get("severity", "warn")
                border = _ALERT_BORDER.get(severity, "yellow")
                emoji = "⚠ " if severity in ("warn", "bad") else ""
                body = "\n".join(alert.get("lines", []))
                if alert.get("action"):
                    body += f"\n[bold]{alert['action']}[/]"
                console.print(
                    Panel(
                        body,
                        title=f"{emoji}{alert.get('title', '')}",
                        border_style=border,
                    )
                )

            # Create info table — every row comes from the shared report.
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Metric", style="dim")
            table.add_column("Value")
            for row in report.get("rows", []):
                style = _TONE_RICH.get(row.get("tone", "default"))
                val = row.get("value", "")
                table.add_row(
                    row.get("label", ""), f"[{style}]{val}[/]" if style else val
                )

            # --verbose embedding-cache extras stay CLI-only (not in the report).
            if verbose and indexing.embedding_cache:
                ec = indexing.embedding_cache
                table.add_row("  Memory Entries", f"{int(ec.get('mem_entries', 0)):,}")
                size_bytes = int(ec.get("size_bytes", 0))
                size_mb = size_bytes / (1024 * 1024) if size_bytes else 0.0
                table.add_row("  Cache Size", f"{size_mb:.2f} MB")

            console.print(table)

            # Web dashboard — always show the pink box (running URL or notice).
            render_dashboard_status(console=console)

    except ConnectionError as e:
        # Dashboard is independent of the project server — surface its box even
        # when this server is down (human output only).
        if not json_output:
            render_dashboard_status(console=console)
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)

    except ServerError as e:
        if json_output:
            import json

            click.echo(json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e
