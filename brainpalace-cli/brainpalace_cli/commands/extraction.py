"""`brainpalace extraction` — drain queue access for the CC subagent executor."""

from __future__ import annotations

import json
import sys

import click

from ..client import (
    ConnectionError,
    DocServeClient,
    ServerError,
    exit_on_connection_error,
)
from ..config import get_server_url


@click.group("extraction")
def extraction_group() -> None:
    """Graph-extraction drain queue (used by the AI drain command)."""


@extraction_group.command("pending")
@click.option("--limit", default=20, show_default=True, help="Maximum items to return.")
@click.option(
    "--source",
    type=click.Choice(["all", "doc", "session"]),
    default="all",
    show_default=True,
    help="Filter the queue: doc (skips the session archive scan), session, or all.",
)
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config)",
)
def pending_command(limit: int, source: str, url: str | None) -> None:
    """Print a bounded batch of pending extraction items as JSON."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = client.get_extraction_pending(limit, source=source)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url)
        return
    except ServerError as e:
        raise click.ClickException(
            f"Server returned an error ({e.status_code})."
        ) from e
    click.echo(json.dumps(result))


@extraction_group.command("text")
@click.argument("chunk_id")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config)",
)
def text_command(chunk_id: str, url: str | None) -> None:
    """Print the text of one pending doc chunk by id as JSON."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = client.get_extraction_text(chunk_id)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url)
        return
    except ServerError as e:
        raise click.ClickException(
            f"Server returned an error ({e.status_code})."
        ) from e
    click.echo(json.dumps(result))


@extraction_group.command("submit")
@click.option(
    "--json",
    "json_path",
    required=True,
    help="Payload JSON file, or '-' for stdin.",
)
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config)",
)
def submit_command(json_path: str, url: str | None) -> None:
    """Submit an extraction payload (doc triplets or session extraction)."""
    if json_path == "-":
        raw = sys.stdin.read()
    else:
        with open(json_path, encoding="utf-8") as fh:
            raw = fh.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON payload: {e}") from e
    if not isinstance(payload, dict):
        raise click.ClickException("Extraction payload must be a JSON object.")
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = client.submit_extraction(payload)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url)
        return
    except ServerError as e:
        raise click.ClickException(
            f"Server rejected the payload ({e.status_code})."
        ) from e
    click.echo(json.dumps(result))
