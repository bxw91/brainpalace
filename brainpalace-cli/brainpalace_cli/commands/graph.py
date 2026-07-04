"""Graph power queries — path / impact / co-change (Plan E)."""

from __future__ import annotations

import json as _json
import sys
from collections.abc import Callable
from typing import Any

import click
from rich.console import Console

from ..client import ConnectionError, DocServeClient, ServerError
from ..config import get_server_url

console = Console()


def _run(
    as_json: bool, call: Callable[[DocServeClient], dict[str, Any]]
) -> dict[str, Any] | None:
    """Execute a client call with the shared --json error contract."""
    try:
        with DocServeClient(get_server_url()) as client:
            data = call(client)
    except ConnectionError as exc:
        if as_json:
            click.echo(_json.dumps({"error": f"server not reachable: {exc}"}))
            sys.exit(1)
        console.print("[red]Server not reachable.[/] Start it with: brainpalace start")
        sys.exit(1)
    except ServerError as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        if as_json:
            click.echo(_json.dumps({"error": detail}))
        else:
            console.print(f"[red]Error:[/] {detail}")
        sys.exit(1)
    if as_json:
        click.echo(_json.dumps(data))
        return None
    return data


@click.group(name="graph")
def graph_group() -> None:
    """Structural graph queries: paths, impact analysis, co-change."""


@graph_group.command("path")
@click.argument("src")
@click.argument("dst")
@click.option("--max-depth", default=6, show_default=True, type=int)
@click.option("--limit", default=5, show_default=True, type=int)
@click.option("--domains", default=None, help="CSV: code,doc,session,git")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def path_cmd(
    src: str,
    dst: str,
    max_depth: int,
    limit: int,
    domains: str | None,
    as_json: bool,
) -> None:
    """Shortest edge paths between two nodes (id or unique name)."""
    data = _run(
        as_json,
        lambda c: c.graph_path(
            src, dst, max_depth=max_depth, limit=limit, domains=domains
        ),
    )
    if data is None:
        return
    if not data["paths"]:
        console.print("No path found within depth limit.")
        return
    names = {n["id"]: n["name"] for n in data.get("nodes", [])}
    for p in data["paths"]:
        hops = " -> ".join(names.get(i, i) for i in p["node_ids"])
        labels = ", ".join(e["label"] or "?" for e in p["edges"])
        console.print(f"[bold]{hops}[/]  [dim]({labels})[/]")


@graph_group.command("impact")
@click.argument("node")
@click.option("--max-depth", default=3, show_default=True, type=int)
@click.option("--predicates", default=None, help="CSV predicate filter")
@click.option("--limit", default=200, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def impact_cmd(
    node: str,
    max_depth: int,
    predicates: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """What transitively depends on NODE (reverse dependency closure)."""
    data = _run(
        as_json,
        lambda c: c.graph_impact(
            node, max_depth=max_depth, predicates=predicates, limit=limit
        ),
    )
    if data is None:
        return
    if not data["nodes"]:
        console.print("No dependents found.")
        return
    for n in data["nodes"]:
        console.print(
            f"d{n['depth']}  [bold]{n['name']}[/] "
            f"[dim]({n.get('label') or '?'} — {n['via_predicate']})[/]"
        )


@graph_group.command("cochange")
@click.argument("node")
@click.option("--min-shared", default=2, show_default=True, type=int)
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def cochange_cmd(node: str, min_shared: int, limit: int, as_json: bool) -> None:
    """Files that historically change together with NODE (git history)."""
    data = _run(
        as_json,
        lambda c: c.graph_cochange(node, min_shared=min_shared, limit=limit),
    )
    if data is None:
        return
    if not data["files"]:
        console.print("No co-change history (is git_indexing enabled?).")
        return
    for f in data["files"]:
        console.print(
            f"x{f['shared_commits']}  [bold]{f['name']}[/]  [dim]{f['file_id']}[/]"
        )
