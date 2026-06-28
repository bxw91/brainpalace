"""Index command for triggering document indexing."""

from pathlib import Path

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


@click.command("index")
@click.argument("folder_path", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option(
    "--chunk-size",
    default=None,
    type=int,
    help="Target chunk size in tokens (advanced; default 512).",
)
@click.option(
    "--chunk-overlap",
    default=None,
    type=int,
    help="Token overlap between chunks (advanced; default 50).",
)
@click.option(
    "--no-recursive",
    is_flag=True,
    help="Don't scan folder recursively",
)
@click.option(
    "--include-code/--no-code",
    "include_code",
    default=True,
    help=(
        "Index source code files alongside documents (default: ON). "
        "Use --no-code for doc-only repos."
    ),
)
@click.option(
    "--languages",
    help="Comma-separated list of programming languages to index",
)
@click.option(
    "--code-strategy",
    default="ast_aware",
    type=click.Choice(["ast_aware", "text_based"]),
    help="Strategy for chunking code files (default: ast_aware)",
)
@click.option(
    "--include-patterns",
    help="Comma-separated additional include patterns (wildcards supported)",
)
@click.option(
    "--include-type",
    "include_type",
    help=(
        "Comma-separated file type presets to include "
        "(e.g., python,docs,typescript). "
        "Use 'brainpalace types list' to see all available presets."
    ),
)
@click.option(
    "--exclude-patterns",
    help="Comma-separated additional exclude patterns (wildcards supported)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force re-indexing even if embedding provider has changed",
)
@click.option(
    "--allow-external",
    is_flag=True,
    help="Allow indexing paths outside the project directory",
)
@click.option(
    "--watch",
    "watch_mode",
    type=click.Choice(["auto", "off"], case_sensitive=False),
    default=None,
    help="Enable ('auto') or disable ('off') live re-index on file changes "
    "for this folder. Default: leave the folder's current setting unchanged.",
)
@click.option(
    "--watch-debounce",
    "watch_debounce_seconds",
    type=int,
    default=None,
    help="Debounce window in seconds before a watched folder re-indexes.",
)
@click.option(
    "--estimate",
    "estimate_only",
    is_flag=True,
    help="Estimate approximate embedding-token usage and exit — do not index.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--yes",
    "-y",
    "yes",
    is_flag=True,
    help="Skip interactive confirmation prompts (e.g. extraction-backlog warning).",
)
def index_command(
    folder_path: str,
    url: str | None,
    chunk_size: int | None,
    chunk_overlap: int | None,
    no_recursive: bool,
    include_code: bool,
    languages: str | None,
    code_strategy: str,
    include_patterns: str | None,
    include_type: str | None,
    exclude_patterns: str | None,
    force: bool,
    allow_external: bool,
    watch_mode: str | None,
    watch_debounce_seconds: int | None,
    estimate_only: bool,
    json_output: bool,
    yes: bool,
) -> None:
    """Index documents from a folder.

    FOLDER_PATH: Path to the folder containing documents to index.
    """
    # Get URL from config if not specified
    resolved_url = url or get_server_url()

    # Resolve to absolute path
    folder = Path(folder_path).resolve()

    # exclude_patterns default comes from the indexing: config block; chunk
    # size/overlap are advanced per-run flags (not config keys) defaulting to the
    # server's built-in values.
    from brainpalace_server.config.indexing_config import load_indexing_config
    from brainpalace_server.config.settings import settings as _settings

    _idx = load_indexing_config()
    if chunk_size is None:
        chunk_size = _settings.DEFAULT_CHUNK_SIZE
    if chunk_overlap is None:
        chunk_overlap = _settings.DEFAULT_CHUNK_OVERLAP

    # Parse comma-separated lists
    languages_list = (
        [lang.strip() for lang in languages.split(",")] if languages else None
    )
    include_patterns_list = (
        [pat.strip() for pat in include_patterns.split(",")]
        if include_patterns
        else None
    )
    include_types_list = (
        [t.strip() for t in include_type.split(",")] if include_type else None
    )
    exclude_patterns_list = (
        [pat.strip() for pat in exclude_patterns.split(",")]
        if exclude_patterns
        else _idx.exclude_patterns
    )

    try:
        with DocServeClient(base_url=resolved_url) as client:
            if estimate_only:
                est = client.estimate_index(
                    folder_path=str(folder),
                    recursive=not no_recursive,
                    include_code=include_code,
                    include_patterns=include_patterns_list,
                    include_types=include_types_list,
                    exclude_patterns=exclude_patterns_list,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                if json_output:
                    import json

                    click.echo(json.dumps(est, indent=2))
                else:
                    from .estimate_util import print_token_estimate

                    print_token_estimate(console, est)
                return

            # Task 4d: interactive backpressure warn before scheduling a new
            # indexing job.  Skip the prompt under --yes / non-interactive.
            if not yes:
                try:
                    from brainpalace_server.config.extraction_config import (
                        load_extraction_config,
                    )

                    _ext_cfg = load_extraction_config()
                    _max_pending = _ext_cfg.max_pending
                    if _max_pending > 0:
                        _status = client.status()
                        _features = _status.features or {}
                        _dge = _features.get("doc_graph_extraction") or {}
                        _pending = int(_dge.get("pending", 0))
                        if _pending >= _max_pending:
                            click.echo(
                                f"Warning: extraction backlog is {_pending} items "
                                f"(>= max_pending={_max_pending}). "
                                "Indexing will add more pending chunks.",
                                err=True,
                            )
                            if not click.confirm(
                                "Extraction backlog is large; index anyway?"
                            ):
                                raise SystemExit(0)
                except (SystemExit, KeyboardInterrupt):
                    raise
                except Exception:  # noqa: BLE001 — never block indexing
                    pass

            response = client.index(
                folder_path=str(folder),
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                recursive=not no_recursive,
                include_code=include_code,
                supported_languages=languages_list,
                code_chunk_strategy=code_strategy,
                include_patterns=include_patterns_list,
                include_types=include_types_list,
                exclude_patterns=exclude_patterns_list,
                force=force,
                allow_external=allow_external,
                watch_mode=watch_mode,
                watch_debounce_seconds=watch_debounce_seconds,
            )

            if json_output:
                import json

                output = {
                    "job_id": response.job_id,
                    "status": response.status,
                    "message": response.message,
                    "folder": str(folder),
                }
                click.echo(json.dumps(output, indent=2))
                return

            console.print("\n[green]Job queued![/]\n")
            console.print(f"[bold]Job ID:[/] {response.job_id}")
            console.print(f"[bold]Folder:[/] {folder}")
            console.print(f"[bold]Status:[/] {response.status}")
            if watch_mode:
                console.print(f"[bold]Watch:[/] {watch_mode}")
            if include_type:
                console.print(f"[bold]Include Types:[/] {include_type}")
            if response.message:
                # Check for duplicate detection message
                if "Duplicate" in (response.message or ""):
                    console.print(f"[yellow]Note:[/] {response.message}")
                else:
                    console.print(f"[bold]Message:[/] {response.message}")

            console.print(
                "\n[dim]Use 'brainpalace jobs' or 'brainpalace jobs --watch' "
                "to monitor progress.[/]"
            )

    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)

    except ServerError as e:
        if json_output:
            import json

            click.echo(json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
            if e.status_code == 429:
                console.print(
                    "\n[dim]The job queue is full. "
                    "Wait for some jobs to complete and try again.[/]"
                )
            elif e.status_code == 409:
                console.print(
                    "\n[dim]A conflict occurred. "
                    "Check 'brainpalace jobs' for queue status.[/]"
                )
        raise SystemExit(1) from e
