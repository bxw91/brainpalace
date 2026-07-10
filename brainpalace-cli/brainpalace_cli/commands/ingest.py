"""Ingest into BrainPalace with caller provenance (spec Item 3 + Round 4).

`ingest` is a default-command group: a bare ``ingest FILE ...`` (or an option
like ``--delete``) routes to the text-ingest default, while ``ingest record``
and ``ingest reference`` are subcommands for the eager/lazy tiers."""

import json as _json
import sys
from pathlib import Path
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


class _DefaultGroup(click.Group):
    """Route any invocation whose first token is not a known subcommand (a FILE
    path, or an option such as ``--delete``) to the ``text`` default command, so
    the pinned ``brainpalace ingest FILE ...`` interface keeps working alongside
    the ``record`` / ``reference`` subcommands."""

    default_command = "text"

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if not args:
            args = [self.default_command]
        elif args[0] not in self.commands and args[0] not in ("--help", "-h"):
            args = [self.default_command, *args]
        return super().parse_args(ctx, args)


@click.group("ingest", cls=_DefaultGroup, no_args_is_help=False)
def ingest_command() -> None:
    """Ingest content into BrainPalace with caller-supplied provenance.

    Bare `ingest FILE --domain ... --source ... --source-id ...` ingests free
    text; `ingest record` / `ingest reference` write the typed / lazy tiers.
    """


def _emit_result(result: Any, json_output: bool) -> None:
    if json_output:
        click.echo(_json.dumps(result, indent=2))
    else:
        console.print(result)


def _handle_server_error(e: ServerError, json_output: bool) -> None:
    if json_output:
        click.echo(_json.dumps({"error": str(e), "detail": e.detail}))
    else:
        console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
    raise SystemExit(1) from e


@ingest_command.command("text", hidden=True)
@click.argument("source_file", required=False)
@click.option(
    "--delete",
    "delete_mode",
    is_flag=True,
    help="Delete all ingested chunks for --source-id instead of ingesting.",
)
@click.option(
    "--forget",
    "forget_mode",
    is_flag=True,
    help=(
        "Full forget: delete --source-id across chunks + records + "
        "references (D2 cascade), instead of ingesting."
    ),
)
@click.option("--domain", help="Registered domain for the text (e.g. home).")
@click.option("--source", help="Producing source (e.g. scanner, email).")
@click.option(
    "--source-id",
    "source_id",
    help="Caller-stable id; re-ingest replaces.",
)
@click.option(
    "--metadata",
    "metadata",
    multiple=True,
    help="Extra k=v chunk metadata (repeatable, string values).",
)
@click.option(
    "--sensitivity",
    default="normal",
    show_default=True,
    help="Sensitivity mark (non-normal rows are hidden by default at query time).",
)
@click.option("--language", default=None, help="BM25 language override (e.g. hr).")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def ingest_text(
    source_file: str | None,
    delete_mode: bool,
    forget_mode: bool,
    domain: str | None,
    source: str | None,
    source_id: str | None,
    metadata: tuple[str, ...],
    sensitivity: str,
    language: str | None,
    url: str | None,
    json_output: bool,
) -> None:
    """Ingest FILE (or '-' for stdin) as searchable text with provenance."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            if delete_mode and forget_mode:
                raise click.UsageError("--delete and --forget are mutually exclusive")
            if forget_mode:
                if not source_id:
                    raise click.UsageError("--forget requires --source-id")
                result = client.ingest_forget(source_id)
            elif delete_mode:
                if not source_id:
                    raise click.UsageError("--delete requires --source-id")
                result = client.ingest_delete(source_id)
            else:
                if not (source_file and domain and source and source_id):
                    raise click.UsageError(
                        "ingest requires FILE (or '-') plus --domain, "
                        "--source and --source-id"
                    )
                text = (
                    sys.stdin.read()
                    if source_file == "-"
                    else Path(source_file).read_text(encoding="utf-8")
                )
                meta: dict[str, str] = {}
                for pair in metadata:
                    k, sep, v = pair.partition("=")
                    if not sep:
                        raise click.UsageError(f"--metadata expects k=v, got: {pair}")
                    meta[k] = v
                result = client.ingest_text(
                    items=[
                        {
                            "text": text,
                            "metadata": meta,
                            "domain": domain,
                            "source": source,
                            "source_id": source_id,
                        }
                    ],
                    sensitivity=sensitivity,
                    language=language,
                )
        _emit_result(result, json_output)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        _handle_server_error(e, json_output)


@ingest_command.command("record")
@click.option("--subject", required=True, help="What the measurement is about.")
@click.option("--metric", required=True, help="The measured quantity name.")
@click.option("--value", required=True, type=float, help="Numeric value.")
@click.option("--unit", default=None, help="Unit of the value (optional).")
@click.option("--ts", default=None, help="ISO-8601 timestamp (optional).")
@click.option("--domain", required=True, help="Registered domain (e.g. home).")
@click.option("--source", required=True, help="Producing source.")
@click.option(
    "--source-id",
    "source_id",
    required=True,
    help="Caller-stable id; re-ingest replaces its records.",
)
@click.option(
    "--confidence",
    type=float,
    default=1.0,
    show_default=True,
    help="Confidence in [0,1]; caller-asserted records default to 1.0.",
)
@click.option(
    "--sensitivity",
    default="normal",
    show_default=True,
    help="Sensitivity mark (non-normal rows are hidden by default at query time).",
)
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def ingest_record(
    subject: str,
    metric: str,
    value: float,
    unit: str | None,
    ts: str | None,
    domain: str,
    source: str,
    source_id: str,
    confidence: float,
    sensitivity: str,
    url: str | None,
    json_output: bool,
) -> None:
    """Ingest one caller-asserted typed record (eager tier)."""
    resolved_url = url or get_server_url()
    item: dict[str, Any] = {
        "subject": subject,
        "metric": metric,
        "value": value,
        "unit": unit,
        "ts": ts,
        "domain": domain,
        "source": source,
        "source_id": source_id,
        "confidence": confidence,
    }
    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = client.ingest_records(items=[item], sensitivity=sensitivity)
        _emit_result(result, json_output)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        _handle_server_error(e, json_output)


@ingest_command.command("reference")
@click.option("--pointer", required=True, help="Opaque pointer to the source.")
@click.option("--summary", default="", help="Short summary used for search.")
@click.option("--domain", required=True, help="Registered domain (e.g. home).")
@click.option("--source", required=True, help="Producing source.")
@click.option(
    "--source-id",
    "source_id",
    required=True,
    help="Caller-stable id; re-ingest replaces its references.",
)
@click.option(
    "--sensitivity",
    default="normal",
    show_default=True,
    help="Sensitivity mark (non-normal rows are hidden by default at query time).",
)
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def ingest_reference(
    pointer: str,
    summary: str,
    domain: str,
    source: str,
    source_id: str,
    sensitivity: str,
    url: str | None,
    json_output: bool,
) -> None:
    """Ingest one lazy-tier reference (pointer + summary)."""
    resolved_url = url or get_server_url()
    item: dict[str, Any] = {
        "pointer": pointer,
        "summary": summary,
        "domain": domain,
        "source": source,
        "source_id": source_id,
    }
    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = client.ingest_references(items=[item], sensitivity=sensitivity)
        _emit_result(result, json_output)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        _handle_server_error(e, json_output)


@ingest_command.command("sources")
@click.option("--domain", default=None, help="Filter by domain.")
@click.option("--source", default=None, help="Filter by raw source label.")
@click.option(
    "--include-sensitive",
    is_flag=True,
    help="Reveal sources whose chunks are marked sensitive (hidden by default).",
)
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def ingest_sources(
    domain: str | None,
    source: str | None,
    include_sensitive: bool,
    url: str | None,
    json_output: bool,
) -> None:
    """List distinct ingested source_ids with provenance + chunk counts."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = client.ingest_sources(
                domain=domain, source=source, include_sensitive=include_sensitive
            )
        _emit_result(result, json_output)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        _handle_server_error(e, json_output)


@ingest_command.command("show")
@click.argument("source_id")
@click.option("--offset", default=0, type=int, show_default=True, help="Page offset.")
@click.option("--limit", default=50, type=int, show_default=True, help="Page size.")
@click.option(
    "--include-sensitive",
    is_flag=True,
    help="Reveal chunks marked sensitive (hidden by default).",
)
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def ingest_show(
    source_id: str,
    offset: int,
    limit: int,
    include_sensitive: bool,
    url: str | None,
    json_output: bool,
) -> None:
    """Show one SOURCE_ID's ingested chunks (id, text, metadata), paginated."""
    resolved_url = url or get_server_url()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            result = client.ingest_show(
                source_id,
                offset=offset,
                limit=limit,
                include_sensitive=include_sensitive,
            )
        _emit_result(result, json_output)
    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)
    except ServerError as e:
        _handle_server_error(e, json_output)
