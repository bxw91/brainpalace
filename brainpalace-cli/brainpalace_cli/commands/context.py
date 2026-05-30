"""`context` command — print the session-start context block (Phase 035)."""

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


@click.command("context")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config)",
)
@click.option("--json", "json_output", is_flag=True, help="Output the structured JSON")
def context_command(url: str | None, json_output: bool) -> None:
    """Print the session-start context block (project facts + curated memory).

    Designed to be run by a SessionStart hook so the AI starts each session with
    the project's durable facts already in context. See docs/SESSION_CONTEXT.md.
    """
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            data = client.session_context()
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        # Fail soft: a hook must never block session start. Print nothing on the
        # block channel; note the reason on stderr.
        click.echo(f"context unavailable ({e.status_code})", err=True)
        return

    if json_output:
        import json

        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(data.get("text", ""))
