"""CLI subcommands for durable taught confidence rules (Phase 5 / CO-3)."""

from __future__ import annotations

import json as _json
from typing import Any, Callable

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


def _url(url: str | None) -> str:
    return url or get_server_url()


_URL_OPT = click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
_JSON_OPT = click.option("--json", "json_output", is_flag=True, help="Output as JSON")


@click.group("rules")
def rules_group() -> None:
    """Manage durable taught confidence rules (compute-mode trust)."""


def _run(
    resolved_url: str,
    json_output: bool,
    fn: Callable[[DocServeClient], Any],
) -> Any:
    try:
        with DocServeClient(base_url=resolved_url) as client:
            return fn(client)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        if json_output:
            click.echo(_json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e


@rules_group.command("list")
@_URL_OPT
@click.option("--all", "show_all", is_flag=True, help="Include retired rules")
@_JSON_OPT
def rules_list(url: str | None, show_all: bool, json_output: bool) -> None:
    """List taught rules (active by default)."""
    resolved = _url(url)

    def _do(client: DocServeClient) -> None:
        r = client._request("GET", "/rules", params={"active": not show_all})
        if json_output:
            click.echo(_json.dumps(r, indent=2))
        else:
            rules = r.get("rules") or []
            if not rules:
                console.print("[dim]no rules[/]")
            for x in rules:
                rng = f"[{x.get('value_min')}, {x.get('value_max')}]"
                console.print(
                    f"[bold]{x['id']}[/] {x['metric']} "
                    f"{x.get('unit') or ''} {rng} -> {x['tier']} "
                    f"(v{x['version']}{' RETIRED' if x['retired_at'] else ''})"
                )

    _run(resolved, json_output, _do)


@rules_group.command("add")
@_URL_OPT
@click.option("--metric", "-m", required=True)
@click.option(
    "--tier",
    "-t",
    required=True,
    type=click.Choice(["HIGH", "PROVISIONAL", "UNVERIFIED"]),
)
@click.option("--unit", "-u", default=None)
@click.option("--min", "value_min", type=float, default=None)
@click.option("--max", "value_max", type=float, default=None)
@click.option("--owner", default="user")
@_JSON_OPT
def rules_add(
    url: str | None,
    metric: str,
    tier: str,
    unit: str | None,
    value_min: float | None,
    value_max: float | None,
    owner: str,
    json_output: bool,
) -> None:
    """Teach a confidence rule (promotes matching records)."""
    resolved = _url(url)
    body = {
        "owner": owner,
        "metric": metric,
        "tier": tier,
        "unit": unit,
        "value_min": value_min,
        "value_max": value_max,
    }

    def _do(client: DocServeClient) -> None:
        r = client._request("POST", "/rules", json=body)
        if json_output:
            click.echo(_json.dumps(r, indent=2))
        else:
            console.print(f"[green]Rule added:[/] {r['id']}")

    _run(resolved, json_output, _do)


@rules_group.command("retire")
@_URL_OPT
@click.argument("rule_id")
@_JSON_OPT
def rules_retire(url: str | None, rule_id: str, json_output: bool) -> None:
    """Retire (soft-delete) a taught rule."""
    resolved = _url(url)

    def _do(client: DocServeClient) -> None:
        r = client._request("POST", f"/rules/{rule_id}/retire")
        if json_output:
            click.echo(_json.dumps(r, indent=2))
        else:
            console.print(
                "[green]Retired.[/]"
                if r.get("retired")
                else "[yellow]No active rule with that id.[/]"
            )

    _run(resolved, json_output, _do)


@rules_group.command("show")
@_URL_OPT
@click.argument("rule_id")
@_JSON_OPT
def rules_show(url: str | None, rule_id: str, json_output: bool) -> None:
    """Show one taught rule by id."""
    resolved = _url(url)

    def _do(client: DocServeClient) -> None:
        r = client._request("GET", f"/rules/{rule_id}")
        click.echo(_json.dumps(r, indent=2))

    _run(resolved, json_output, _do)
