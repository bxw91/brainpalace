"""`backfill-sessions` — summarize OLD chats in either engine (Phase 080).

In **subagent** mode summarization is **archive-driven**: old sessions are
archived under ``<project>/.brainpalace/session_archive/`` and the drain
unified per-prompt drain picks them up automatically once quiescent — there is
no queue to seed, so this command just
confirms archiving is on and reports how many transcripts are present. In
**provider** mode it calls ``POST /sessions/distill`` so the server distils each
transcript (``--force`` re-distils already-marked ones). Provider mode is largely
redundant with the server's catch-up sweep; this command is the on-demand /
forced entry point.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import yaml
from rich.console import Console

from ..client import (
    ConnectionError,
    DocServeClient,
    ServerError,
    exit_on_connection_error,
)
from ..config import get_server_url
from ..discovery import discover_project_dir
from .plugin_detect import claude_plugin_installed

console = Console()


def read_extract_mode(project_root: Path) -> str:
    """Resolve ``extraction.mode`` from project config (default off, cost-safe).

    Reads the shared ``extraction:`` block — the sole engine selector for both
    doc-graph and session distillation. Absent, unparseable, or invalid blocks
    resolve to ``off`` so a missing config can never push backfill onto the
    billable server engine. ``off`` means nothing to backfill.
    """
    config_path = project_root / ".brainpalace" / "config.yaml"
    if not config_path.exists():
        return "off"
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError:
        return "off"
    block = data.get("extraction") if isinstance(data, dict) else None
    mode = block.get("mode") if isinstance(block, dict) else None
    if mode is False:  # YAML 1.1: unquoted `off` → bool
        return "off"
    return mode if mode in ("auto", "subagent", "provider", "off") else "off"


def default_sessions_dir(project_root: Path) -> Path:
    """The Claude Code transcript dir for a project (encoded-cwd under ~/.claude)."""
    from brainpalace_server.services.session_index_service import (
        encode_project_to_sessions_dir,
    )

    return Path(encode_project_to_sessions_dir(str(project_root)))


def discover_transcripts(from_dir: Path, limit: int | None) -> list[Path]:
    """``*.jsonl`` transcripts under ``from_dir``, newest first, capped at ``limit``."""
    if not from_dir.is_dir():
        return []
    files = sorted(
        from_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    return files[:limit] if limit else files


@click.command("backfill-sessions")
@click.option(
    "--project",
    "-p",
    type=click.Path(file_okay=False),
    default=None,
    help="Project root (default: discover .brainpalace/ from cwd).",
)
@click.option(
    "--from-dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Transcript dir (default: the Claude Code dir for this project).",
)
@click.option("--limit", type=int, default=None, help="Cap the number of transcripts.")
@click.option(
    "--force",
    is_flag=True,
    help="Provider mode: re-distil already-summarized sessions.",
)
@click.option("--url", envvar="BRAINPALACE_URL", default=None, help="Server URL.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def backfill_command(
    project: str | None,
    from_dir: str | None,
    limit: int | None,
    force: bool,
    url: str | None,
    json_output: bool,
) -> None:
    """Summarize this project's OLD chat sessions in the configured engine."""
    project_root = (
        Path(project).resolve() if project else discover_project_dir(Path.cwd())
    )
    if project_root is None:
        raise click.ClickException(
            "No .brainpalace/ project found; pass --project <path>."
        )

    mode = read_extract_mode(project_root)
    if mode == "auto":
        mode = (
            "subagent" if claude_plugin_installed(project=project_root) else "provider"
        )
    if mode == "off":
        msg = "extraction.mode is 'off' — nothing to backfill."
        click.echo(json.dumps({"status": "off"}) if json_output else msg)
        return

    base = Path(from_dir) if from_dir else default_sessions_dir(project_root)
    transcripts = discover_transcripts(base, limit)
    if not transcripts:
        msg = f"No transcripts found in {base}."
        click.echo(
            json.dumps({"status": "empty", "from_dir": str(base)})
            if json_output
            else msg
        )
        return

    if mode == "subagent":
        # Archive-driven: no queue to seed. The drain gap-selector summarizes
        # archived sessions automatically once they are quiescent.
        found = len(transcripts)
        if json_output:
            click.echo(
                json.dumps({"status": "archive-driven", "mode": mode, "found": found})
            )
        else:
            console.print(
                f"[green]Archive-driven summarization is on[/] — {found} transcript(s) "
                "present; the per-prompt drain summarizes archived sessions "
                "automatically once they are quiescent."
            )
        return

    # provider mode → server route
    resolved_url = url or get_server_url()
    paths = [str(t) for t in transcripts]
    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = client.submit_session_distill(paths, force=force)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url)
        return
    except ServerError as e:
        raise click.ClickException(
            f"Server rejected the request ({e.status_code}): provider engine may "
            "not be active (mode != provider or kill switch off)."
        ) from e

    if json_output:
        click.echo(json.dumps({"status": "enqueued", "mode": mode, **result}))
    else:
        console.print(
            f"[green]Enqueued {result.get('enqueued', 0)} transcript(s)[/] for "
            f"provider-engine distillation (force={result.get('force', force)})."
        )
