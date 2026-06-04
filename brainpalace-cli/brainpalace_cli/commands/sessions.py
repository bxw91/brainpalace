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


@click.command("session-path")
@click.argument("session_id")
@click.option(
    "--project",
    "-p",
    type=click.Path(file_okay=False),
    default=None,
    help="Project root (default: discover .brainpalace/ from cwd).",
)
def session_path_command(session_id: str, project: str | None) -> None:
    """Print the ARCHIVED transcript path for a session id (empty if unarchived).

    Reads ``.brainpalace/session_archive/manifest.json``. Prints nothing (exit 0)
    when the session is not archived, so a caller can fall back to the live dir.
    """
    from pathlib import Path

    from ..discovery import discover_project_dir

    root = Path(project).resolve() if project else discover_project_dir(Path.cwd())
    if root is None:
        return
    manifest = root / ".brainpalace" / "session_archive" / "manifest.json"
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return
    # Top-level entry: key == session_id (subagents use composite keys).
    entry = data.get(session_id) if isinstance(data, dict) else None
    if isinstance(entry, dict):
        ap = entry.get("archive_path")
        if ap and Path(ap).is_file():
            click.echo(ap)
