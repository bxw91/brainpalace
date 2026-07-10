"""CLI subcommands for the reference catalog (Round 2 Plan C): list, semantic
search, resolve a reference to its pointer, and backfill missing embeddings."""

from __future__ import annotations

import json as _json

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

_URL_OPTION = click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)


def _handle_server_error(e: ServerError, json_output: bool) -> None:
    if json_output:
        click.echo(_json.dumps({"error": str(e), "detail": e.detail}))
    else:
        console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
    raise SystemExit(1) from e


@click.group("references")
def references_group() -> None:
    """Search and manage the lazy-tier reference catalog."""


@references_group.command("list")
@_URL_OPTION
@click.option("--domain", default=None, help="Filter references by domain.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def references_list(url: str | None, domain: str | None, json_output: bool) -> None:
    """List references, optionally filtered by --domain."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            r = client.references_list(domain)
        if json_output:
            click.echo(_json.dumps(r, indent=2))
        else:
            refs = r.get("references", [])
            if not refs:
                console.print("[dim]No references.[/]")
            for ref in refs:
                console.print(
                    f"[bold]{ref['id']}[/] [{ref['domain']}] "
                    f"{ref['pointer']} — {ref.get('summary', '')}"
                )
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        _handle_server_error(e, json_output)


@references_group.command("search")
@click.argument("query")
@_URL_OPTION
@click.option("--top-k", "top_k", default=5, show_default=True, help="Max hits.")
@click.option("--domain", default=None, help="Restrict search to this domain.")
@click.option(
    "--include-sensitive",
    is_flag=True,
    help="Reveal references marked sensitivity != 'normal' (default: hidden).",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def references_search(
    query: str,
    url: str | None,
    top_k: int,
    domain: str | None,
    include_sensitive: bool,
    json_output: bool,
) -> None:
    """Semantic search over reference summaries for QUERY."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            r = client.references_search(
                query=query,
                top_k=top_k,
                domain=domain,
                include_sensitive=include_sensitive,
            )
        if json_output:
            click.echo(_json.dumps(r, indent=2))
        else:
            results = r.get("results", [])
            if not results:
                console.print("[dim]No matching references.[/]")
            for hit in results:
                score = hit.get("score", 0.0)
                console.print(
                    f"[bold]{score:.3f}[/] {hit['pointer']} — "
                    f"{hit.get('summary', '')}"
                )
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        _handle_server_error(e, json_output)


@references_group.command("resolve")
@click.argument("reference_id")
@_URL_OPTION
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def references_resolve(reference_id: str, url: str | None, json_output: bool) -> None:
    """Print the stored pointer + summary for REFERENCE_ID."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            r = client.references_list()
        match = next(
            (ref for ref in r.get("references", []) if ref["id"] == reference_id),
            None,
        )
        if match is None:
            if json_output:
                click.echo(_json.dumps({"error": "not found", "id": reference_id}))
            else:
                console.print(f"[red]No reference with id {reference_id}[/]")
            raise SystemExit(1)
        if json_output:
            click.echo(_json.dumps(match, indent=2))
        else:
            console.print(f"[bold]pointer:[/] {match['pointer']}")
            console.print(f"[bold]summary:[/] {match.get('summary', '')}")
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        _handle_server_error(e, json_output)


@references_group.command("embed-missing")
@_URL_OPTION
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def references_embed_missing(url: str | None, json_output: bool) -> None:
    """Backfill embeddings for references that lack one."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            r = client.references_embed_missing()
        if json_output:
            click.echo(_json.dumps(r, indent=2))
        else:
            console.print(f"[green]Embedded {r.get('embedded', 0)} reference(s).[/]")
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        _handle_server_error(e, json_output)
