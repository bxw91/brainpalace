"""`submit-session` command — persist a session extraction payload (Phase 060).

The extraction JSON is produced by the AI coding tool (the manual command in
070, the SessionEnd subagent in 080); this command just ships it to the server's
``POST /sessions/extract``. Read the payload from a file or stdin (``-``).
"""

import json
import sys

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


@click.command("submit-session")
@click.argument("session_id", required=False)
@click.option(
    "--json",
    "json_path",
    required=True,
    help="Path to the extraction JSON, or '-' to read from stdin.",
)
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config)",
)
def submit_session_command(
    session_id: str | None, json_path: str, url: str | None
) -> None:
    """Submit a session extraction payload to the server.

    SESSION_ID (optional) overrides/sets the payload's session_id. The payload
    must match the extraction schema (see docs/SESSION_INDEXING.md).
    """
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
    if session_id:
        payload["session_id"] = session_id

    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = client.submit_session_extract(payload)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url)
        return
    except ServerError as e:
        raise click.ClickException(
            f"Server rejected the payload ({e.status_code})."
        ) from e

    console.print(
        f"[green]Stored session[/] {result.get('session_id')}: "
        f"{result.get('summary_chunks', 0)} summary + "
        f"{result.get('decision_chunks', 0)} decision chunk(s), "
        f"{result.get('triplets_stored', 0)} triplet(s)"
        + (", digest updated" if result.get("digest_updated") else "")
    )
