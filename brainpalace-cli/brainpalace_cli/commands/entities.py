"""Identity commands (G5): person / alias / link over the engine's identity
store. The engine stores and RANKS candidates; it never picks a winner — the
consumer app decides (D7).

``--json`` contract (mirrors ``ingest``): on success the result dict is printed;
on failure a ``{"error": ...}`` object is printed with a non-zero exit and NO
``results`` key."""

import json as _json
from collections.abc import Callable
from typing import Any

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


def _emit(result: dict[str, Any], json_output: bool) -> None:
    if json_output:
        click.echo(_json.dumps(result, indent=2))
    else:
        console.print(result)


def _run(
    resolved_url: str,
    json_output: bool,
    fn: Callable[[DocServeClient], dict[str, Any]],
) -> None:
    """Execute ``fn(client)`` with the shared connection/error handling and
    the ``--json`` failure contract."""
    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = fn(client)
        _emit(result, json_output)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        if json_output:
            click.echo(_json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e


_URL = click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
_JSON = click.option("--json", "json_output", is_flag=True, help="Output as JSON")


@click.group("entities")
def entities_group() -> None:
    """Manage identity: person / alias / link (who someone is)."""


@entities_group.command("person")
@click.option("--id", "person_id", default=None, help="Existing person id (upsert).")
@click.option("--name", default=None, help="Display name (omit for an unknown person).")
@click.option("--kind", default="person", show_default=True, help="person|place|org.")
@click.option("--domain", required=True, help="Domain the person belongs to.")
@click.option("--sensitivity", default="normal", show_default=True)
@_URL
@_JSON
def person_cmd(
    person_id: str | None,
    name: str | None,
    kind: str,
    domain: str,
    sensitivity: str,
    url: str | None,
    json_output: bool,
) -> None:
    """Upsert a person (naming an unknown one is an update in place)."""
    resolved_url = url or get_server_url()
    body = {"kind": kind, "domain": domain, "sensitivity": sensitivity}
    if person_id:
        body["id"] = person_id
    if name is not None:
        body["name"] = name
    _run(resolved_url, json_output, lambda c: c.entities_person(body))


@entities_group.command("alias")
@click.option("--surface", required=True, help='Surface string, e.g. "Mama".')
@click.option(
    "--person-id", "person_id", required=True, help="Person the surface names."
)
@click.option("--scope", default=None, help="Speaker person id; omit for global.")
@click.option("--valid-from", "valid_from", default=None)
@click.option("--valid-to", "valid_to", default=None)
@_URL
@_JSON
def alias_cmd(
    surface: str,
    person_id: str,
    scope: str | None,
    valid_from: str | None,
    valid_to: str | None,
    url: str | None,
    json_output: bool,
) -> None:
    """Bind a surface to a person (scoped + time-bounded)."""
    resolved_url = url or get_server_url()
    body = {"surface": surface, "person_id": person_id}
    if scope is not None:
        body["scope"] = scope
    if valid_from is not None:
        body["valid_from"] = valid_from
    if valid_to is not None:
        body["valid_to"] = valid_to
    _run(resolved_url, json_output, lambda c: c.entities_alias(body))


@entities_group.command("link")
@click.option(
    "--ref", required=True, help="chunk address, session id, or external key."
)
@click.option(
    "--ref-kind", "ref_kind", required=True, help="chunk|span|session|external."
)
@click.option("--role", required=True, help="speaker|mentioned|participant.")
@click.option(
    "--method", required=True, help="user_asserted|call_log|llm_inferred|alias_match."
)
@click.option("--at", required=True, help="Mention timestamp (ISO-8601).")
@click.option(
    "--person-id", "person_id", default=None, help="Resolved person; omit = unresolved."
)
@click.option("--span-start", "span_start", type=int, default=None)
@click.option("--span-end", "span_end", type=int, default=None)
@click.option("--surface", default=None, help="Surface being resolved (for backfill).")
@click.option("--scope", default=None, help="Scope of that surface (for backfill).")
@click.option("--confidence", type=float, default=None)
@_URL
@_JSON
def link_cmd(
    ref: str,
    ref_kind: str,
    role: str,
    method: str,
    at: str,
    person_id: str | None,
    span_start: int | None,
    span_end: int | None,
    surface: str | None,
    scope: str | None,
    confidence: float | None,
    url: str | None,
    json_output: bool,
) -> None:
    """Attach a ref to a person, or record it unresolved."""
    resolved_url = url or get_server_url()
    body: dict[str, Any] = {
        "ref": ref,
        "ref_kind": ref_kind,
        "role": role,
        "method": method,
        "at": at,
    }
    if person_id is not None:
        body["person_id"] = person_id
    if span_start is not None:
        body["span_start"] = span_start
    if span_end is not None:
        body["span_end"] = span_end
    if surface is not None:
        body["surface"] = surface
    if scope is not None:
        body["scope"] = scope
    if confidence is not None:
        body["confidence"] = confidence
    _run(resolved_url, json_output, lambda c: c.entities_link(body))


@entities_group.command("resolve")
@click.option("--surface", required=True, help="Surface string to resolve.")
@click.option("--scope", default=None, help="Speaker person id; omit for global.")
@click.option("--at", default=None, help="Resolution timestamp (defaults to now).")
@click.option("--ref", default=None, help="Chunk/session ref for co-occurrence.")
@click.option("--session-id", "session_id", default=None, help="Session for recency.")
@_URL
@_JSON
def resolve_cmd(
    surface: str,
    scope: str | None,
    at: str | None,
    ref: str | None,
    session_id: str | None,
    url: str | None,
    json_output: bool,
) -> None:
    """Ranked candidates + evidence. Never picks a winner."""
    resolved_url = url or get_server_url()
    _run(
        resolved_url,
        json_output,
        lambda c: c.entities_resolve(
            surface=surface, scope=scope, at=at, ref=ref, session_id=session_id
        ),
    )


@entities_group.command("unresolved")
@_URL
@_JSON
def unresolved_cmd(url: str | None, json_output: bool) -> None:
    """List unresolved links (the bucket the app must decide or ask about)."""
    resolved_url = url or get_server_url()
    _run(resolved_url, json_output, lambda c: c.entities_unresolved())


@entities_group.command("backfill")
@_URL
@_JSON
def backfill_cmd(url: str | None, json_output: bool) -> None:
    """Re-score unresolved links against the current aliases."""
    resolved_url = url or get_server_url()
    _run(resolved_url, json_output, lambda c: c.entities_backfill())
