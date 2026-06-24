"""Query command for searching documents."""

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ..client import (
    ConnectionError,
    DocServeClient,
    ServerError,
    exit_on_connection_error,
)
from ..config import get_server_url

console = Console()


def _get_default_url() -> str:
    """Get default server URL from config."""
    return get_server_url()


def _ai_hint_enabled() -> bool:
    """Whether to print the one-line AI-guidance hint. Fail-soft → default on.

    Disabled by ``BRAINPALACE_NO_AI_HINT`` (env) or ``cli.show_ai_hint: false``
    in config. Pull path for CLI-only external agents (see AI-guidance parity).
    """
    import os

    if os.environ.get("BRAINPALACE_NO_AI_HINT"):
        return False
    try:
        from ..config import _find_config_file, _load_yaml_config

        path = _find_config_file()
        if path is not None:
            cfg = _load_yaml_config(path) or {}
            if (cfg.get("cli") or {}).get("show_ai_hint") is False:
                return False
    except Exception:
        pass
    return True


def _maybe_print_ai_hint() -> None:
    """Print the AI-guidance hint on an interactive (TTY) human-format run only.

    Never on ``--json`` (that branch returns earlier) or piped/scripted output —
    keeps the documented JSON contract and scripts clean.
    """
    import sys

    if sys.stdout.isatty() and _ai_hint_enabled():
        console.print(
            "\n[dim]↳ AI agents: run 'brainpalace ai-guide' for search rules "
            "& modes.[/]"
        )


@click.command("query")
@click.argument("query_text")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option(
    "-k",
    "--top-k",
    default=5,
    type=int,
    help="Number of results to return (default: 5)",
)
@click.option(
    "-t",
    "--threshold",
    default=0.3,
    type=float,
    help="Minimum similarity threshold 0-1 (default: 0.3)",
)
@click.option(
    "-m",
    "--mode",
    default="hybrid",
    type=click.Choice(
        ["vector", "bm25", "hybrid", "graph", "multi", "compute"], case_sensitive=False
    ),
    help=(
        "Retrieval mode: 'vector' (semantic similarity), 'bm25' (keyword matching), "
        "'hybrid' (vector+bm25), 'graph' (knowledge graph relationships, requires "
        "ENABLE_GRAPH_INDEX=true), 'multi' (fusion of vector+bm25+graph), "
        "'compute' (set-level aggregation over typed numeric records, requires "
        "ENABLE_COMPUTE=true). Default: hybrid."
    ),
)
@click.option(
    "-a",
    "--alpha",
    default=0.5,
    type=float,
    help="Weight for hybrid search (1.0 = pure vector, 0.0 = pure bm25, default: 0.5)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--full", is_flag=True, help="Show full text content")
@click.option("--scores", is_flag=True, help="Show individual vector/BM25 scores")
@click.option(
    "--source-types",
    help="Comma-separated source types to filter by (doc,code,test)",
)
@click.option(
    "--languages",
    help="Comma-separated programming languages to filter by",
)
@click.option(
    "--file-paths",
    help="Comma-separated file path patterns to filter by (wildcards supported)",
)
@click.option(
    "--no-time-decay",
    is_flag=True,
    help="Disable age-weighted ranking for this query (newer-ranked-higher).",
)
@click.option(
    "--language",
    "query_language",
    default=None,
    help=(
        "BM25 query language override (ISO 639-1, e.g. en, de, hr). "
        "Overrides the project bm25.language for this query only."
    ),
)
def query_command(
    query_text: str,
    url: str | None,
    top_k: int,
    threshold: float,
    mode: str,
    alpha: float,
    json_output: bool,
    full: bool,
    scores: bool,
    source_types: str | None,
    languages: str | None,
    file_paths: str | None,
    no_time_decay: bool,
    query_language: str | None,
) -> None:
    """Search indexed documents with natural language or keyword query.

    \b
    --json output schema (stdout):
      {
        "query": "<text>",
        "total_results": <int>,
        "query_time_ms": <float>,
        "results": [
          {"text": "<chunk snippet>", "source": "<file path>",
           "score": <float>, "chunk_id": "<id>"}
        ]
      }

    Per-result keys are "text" and "source" (NOT "content"/"file_path").

    \b
    On failure --json instead emits {"error": "...", "detail": ..., "hint":
    "..."} (no "results" key) AND exits non-zero. Consumers must check the
    exit code, not just the presence of "results".
    """
    # Get URL from config if not specified
    resolved_url = url or _get_default_url()

    # Parse comma-separated lists
    source_types_list = (
        [st.strip() for st in source_types.split(",")] if source_types else None
    )
    languages_list = (
        [lang.strip() for lang in languages.split(",")] if languages else None
    )
    file_paths_list = (
        [fp.strip() for fp in file_paths.split(",")] if file_paths else None
    )

    try:
        with DocServeClient(base_url=resolved_url) as client:
            response = client.query(
                query_text=query_text,
                top_k=top_k,
                similarity_threshold=threshold,
                mode=mode.lower(),
                alpha=alpha,
                source_types=source_types_list,
                languages=languages_list,
                file_paths=file_paths_list,
                time_decay=not no_time_decay,
                language=query_language,
            )

            if json_output:
                import json

                output: dict[str, object] = {
                    "query": query_text,
                    "total_results": response.total_results,
                    "query_time_ms": response.query_time_ms,
                    "results": [
                        {
                            "text": r.text,
                            "source": r.source,
                            "score": r.score,
                            "chunk_id": r.chunk_id,
                        }
                        for r in response.results
                    ],
                }
                if response.compute is not None:
                    import dataclasses

                    output["compute"] = [
                        dataclasses.asdict(c) for c in response.compute
                    ]
                click.echo(json.dumps(output, indent=2))
                return

            # Compute mode: print aggregation rows as label: value lines
            if response.compute is not None:
                console.print(
                    f"\n[bold]Query:[/] {query_text}\n"
                    f"[dim]Compute results in {response.query_time_ms:.1f}ms[/]\n"
                )
                if not response.compute:
                    console.print("[yellow]No compute results.[/]")
                else:
                    for row in response.compute:
                        unit_suffix = f" {row.unit}" if row.unit else ""
                        console.print(f"[bold]{row.label}:[/] {row.value}{unit_suffix}")
                _maybe_print_ai_hint()
                return

            # Display header
            console.print(
                f"\n[bold]Query:[/] {query_text}\n"
                f"[dim]Found {response.total_results} results "
                f"in {response.query_time_ms:.1f}ms[/]\n"
            )

            if not response.results:
                console.print("[yellow]No matching documents found.[/]")
                console.print(
                    "\n[dim]Tips:\n"
                    "  - Try different keywords\n"
                    "  - Lower the threshold with --threshold 0.1\n"
                    "  - Check if documents are indexed with 'status' command[/]"
                )
                return

            # Display results
            for i, result in enumerate(response.results, 1):
                # Score color based on value
                if result.score >= 0.9:
                    score_color = "green"
                elif result.score >= 0.8:
                    score_color = "yellow"
                else:
                    score_color = "orange3"

                # Truncate text if not showing full
                text = result.text
                if not full and len(text) > 300:
                    text = text[:300] + "..."

                # Create result panel
                header = Text()
                header.append(f"[{i}] ", style="bold cyan")
                header.append(result.source, style="bold")
                header.append("  Score: ", style="dim")
                header.append(f"{result.score:.2%}", style=f"bold {score_color}")

                if scores:
                    header.append("  [V: ", style="dim")
                    v_score = result.metadata.get("vector_score") or getattr(
                        result, "vector_score", None
                    )
                    header.append(
                        f"{v_score:.2f}" if v_score is not None else "N/A", style="dim"
                    )
                    header.append(" B: ", style="dim")
                    b_score = result.metadata.get("bm25_score") or getattr(
                        result, "bm25_score", None
                    )
                    header.append(
                        f"{b_score:.2f}" if b_score is not None else "N/A", style="dim"
                    )
                    header.append("]", style="dim")

                console.print(
                    Panel(
                        text,
                        title=header,
                        border_style="dim",
                        padding=(0, 1),
                    )
                )

            _maybe_print_ai_hint()

    except ConnectionError as e:
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)

    except ServerError as e:
        if json_output:
            import json

            click.echo(
                json.dumps(
                    {
                        "error": str(e),
                        "detail": e.detail,
                        # Failure-time schema hint: broken consumer scripts are
                        # guaranteed to be looking at this payload, so teach the
                        # success shape here (raw CLI users have no other push
                        # channel — they never run --help).
                        "hint": (
                            "On success, results use keys "
                            "text/source/score/chunk_id (no file_path, no "
                            "line numbers). On failure there is no 'results' "
                            "key and the exit code is non-zero — check both."
                        ),
                    }
                )
            )
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
            if e.status_code == 503:
                console.print(
                    "\n[dim]The server is not ready. "
                    "Use 'status' to check, or 'index' to index documents.[/]"
                )
        raise SystemExit(1) from e
