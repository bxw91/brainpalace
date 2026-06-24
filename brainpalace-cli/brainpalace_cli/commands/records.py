"""CLI subcommands for record store stats and revalidation (Task 15)."""

from __future__ import annotations

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


@click.group("records")
def records_group() -> None:
    """Manage typed numeric records (compute mode)."""


@records_group.command("stats")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def records_stats(url: str | None, json_output: bool) -> None:
    """Show record store statistics (total, unverified, metrics)."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            r = client._request("GET", "/records/stats")
            if json_output:
                import json as _json

                click.echo(_json.dumps(r, indent=2))
            else:
                console.print(f"[bold]Total records:[/]    {r['total']}")
                console.print(f"[bold]Unverified (<0.7):[/] {r['unverified']}")
                metrics = r.get("metrics") or []
                console.print(
                    "[bold]Metrics:[/]           "
                    + (", ".join(metrics) if metrics else "[dim]none[/]")
                )
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        if json_output:
            import json as _json

            click.echo(_json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e


@records_group.command("revalidate")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option(
    "--metric",
    "-m",
    default=None,
    help="Restrict rescoring to this metric only (default: all unverified records).",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def records_revalidate(url: str | None, metric: str | None, json_output: bool) -> None:
    """Re-score low-confidence records, optionally filtered by metric."""
    resolved_url = url or get_server_url()
    body: dict[str, str] = {}
    if metric is not None:
        body["metric"] = metric
    try:
        with DocServeClient(base_url=resolved_url) as client:
            r = client._request("POST", "/records/revalidate", json=body)
            if json_output:
                import json as _json

                click.echo(_json.dumps(r, indent=2))
            else:
                console.print(f"[green]Rescored {r['rescored']} record(s).[/]")
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        if json_output:
            import json as _json

            click.echo(_json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e
