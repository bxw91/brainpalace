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
from ..merge import rrf_merge

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


def _resolve_instance_url(value: str) -> str | None:
    """Resolve an ``--also`` value to a reachable sibling base URL.

    A value starting with ``http`` is used as-is. Otherwise it's treated as
    a project path: resolved to its absolute root and looked up in the
    running registry (the same source ``brainpalace list`` reads — see
    ``commands/list_cmd.py``) to find the live server's ``base_url``.
    Returns ``None`` when the path is not a known, currently-running
    instance (the caller degrades gracefully — warn and skip).
    """
    if value.startswith("http"):
        return value

    from pathlib import Path

    from .list_cmd import get_registry, read_runtime

    root = str(Path(value).resolve())
    entry = get_registry().get(root)
    if entry is None:
        return None
    state_dir = Path(entry.get("state_dir", ""))
    runtime = read_runtime(state_dir)
    if not runtime:
        return None
    base_url = runtime.get("base_url")
    return base_url if base_url else None


def _result_to_dict(r: object) -> dict[str, object]:
    """Convert a ``QueryResult`` to the plain-dict shape ``rrf_merge`` wants."""
    return {
        "text": r.text,  # type: ignore[attr-defined]
        "source": r.source,  # type: ignore[attr-defined]
        "score": r.score,  # type: ignore[attr-defined]
        "chunk_id": r.chunk_id,  # type: ignore[attr-defined]
    }


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
        [
            "vector",
            "bm25",
            "hybrid",
            "graph",
            "multi",
            "compute",
            "scan",
            "absence",
            "timeline",
        ],
        case_sensitive=False,
    ),
    help=(
        "Retrieval mode: 'vector' (semantic similarity), 'bm25' (keyword matching), "
        "'hybrid' (vector+bm25), 'graph' (knowledge graph relationships; empty "
        "unless the graph is built — ENABLE_GRAPH_INDEX gates building it), "
        "'multi' (fusion of vector+bm25+graph), "
        "'compute' (set-level aggregation over typed numeric records; empty "
        "unless record extraction has populated them), "
        "'scan' (deterministic term counts over the archived session "
        "transcripts; 'which week did I mention X most'; empty when the "
        "session archive is off), "
        "'absence' (anti-join over typed records: subjects present under one "
        "partition value but absent under another, e.g. 'distance but not "
        "duration'; empty when no two stored values resolve), "
        "'timeline' (walk an entity's edge-validity/supersession history: "
        "how a belief/fact evolved, e.g. 'how did the auth decision evolve'; "
        "empty when the named entity resolves to no graph node), "
        "Default: hybrid."
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
    "--domain",
    "domains",
    multiple=True,
    help=(
        "Filter to chunks ingested under this domain (the reserved `domain` "
        "metadata key set by /ingest — an owner or app namespace). "
        "Repeatable; OR across values."
    ),
)
@click.option(
    "--meta",
    "metadata_pairs",
    multiple=True,
    help=(
        "Filter to chunks whose metadata exact-matches key=value. "
        "Repeatable; AND across keys. Example: --meta owner=alice --meta kind=log"
    ),
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
@click.option(
    "--include-sensitive",
    is_flag=True,
    help="Reveal rows marked sensitive (interactive CLI only; hidden by default).",
)
@click.option(
    "--also",
    "also_paths",
    multiple=True,
    help=(
        "Fan out to a sibling BrainPalace instance (project path or URL) and "
        "RRF-merge its results with the local ones (household multi-instance "
        "M1). Repeatable. A path is resolved via the running-instance "
        "registry ('brainpalace list'); an unreachable/unresolvable sibling "
        "prints a warning and is skipped — local results still render."
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
    domains: tuple[str, ...],
    metadata_pairs: tuple[str, ...],
    no_time_decay: bool,
    query_language: str | None,
    include_sensitive: bool,
    also_paths: tuple[str, ...],
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
    Optional top-level "index_blocked" key (present only when an indexing job is
    paused over the embedding-token budget — the index may be STALE):
      {"job_id": "<id>", "folder_path": "<path>", "estimated_tokens": <int>,
       "limit": <int>, "blocked_since": "<iso>"}
    Approve to continue: brainpalace jobs <job_id> --approve.

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
    domains_list = list(domains) if domains else None

    metadata_filter_dict: dict[str, str] | None = None
    if metadata_pairs:
        metadata_filter_dict = {}
        for pair in metadata_pairs:
            key, sep, value = pair.partition("=")
            if not sep:
                raise click.UsageError(f"--meta expects key=value, got '{pair}'")
            metadata_filter_dict[key.strip()] = value.strip()

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
                domains=domains_list,
                metadata_filter=metadata_filter_dict,
                time_decay=not no_time_decay,
                language=query_language,
                include_sensitive=include_sensitive,
            )

            # Multi-instance fan-out (household M1). Only applies to the
            # standard results-list contract — compute/scan/absence/timeline
            # modes have no per-chunk_id RRF story, so --also is a no-op for
            # them and the single-instance response renders as usual below.
            simple_results_mode = (
                response.compute is None
                and response.scan is None
                and response.absence is None
                and response.timeline is None
            )
            if also_paths and simple_results_mode:
                result_lists: list[tuple[str, list[dict[str, object]]]] = [
                    ("local", [_result_to_dict(r) for r in response.results])
                ]
                for also_value in also_paths:
                    sibling_url = _resolve_instance_url(also_value)
                    if sibling_url is None:
                        click.echo(
                            f"Warning: could not resolve sibling instance "
                            f"'{also_value}' (not a URL and not a known "
                            f"running project) — skipping.",
                            err=True,
                        )
                        continue
                    try:
                        with DocServeClient(base_url=sibling_url) as sibling:
                            sibling_response = sibling.query(
                                query_text=query_text,
                                top_k=top_k,
                                similarity_threshold=threshold,
                                mode=mode.lower(),
                                alpha=alpha,
                                source_types=source_types_list,
                                languages=languages_list,
                                file_paths=file_paths_list,
                                domains=domains_list,
                                metadata_filter=metadata_filter_dict,
                                time_decay=not no_time_decay,
                                language=query_language,
                                include_sensitive=include_sensitive,
                            )
                    except ConnectionError as e:
                        click.echo(
                            f"Warning: sibling instance '{also_value}' "
                            f"({sibling_url}) is unreachable — skipping. "
                            f"({e})",
                            err=True,
                        )
                        continue
                    result_lists.append(
                        (
                            also_value,
                            [_result_to_dict(r) for r in sibling_response.results],
                        )
                    )

                merged = rrf_merge(result_lists, top_k=top_k)

                if json_output:
                    import json

                    click.echo(
                        json.dumps(
                            {
                                "query": query_text,
                                "total_results": len(merged),
                                "query_time_ms": response.query_time_ms,
                                "results": merged,
                            },
                            indent=2,
                        )
                    )
                    return

                console.print(
                    f"\n[bold]Query:[/] {query_text}\n"
                    f"[dim]Merged {len(merged)} results across "
                    f"{len(result_lists)} instance(s)[/]\n"
                )
                if not merged:
                    console.print("[yellow]No matching documents found.[/]")
                    return
                for i, r in enumerate(merged, 1):
                    text = str(r.get("text", ""))
                    if not full and len(text) > 300:
                        text = text[:300] + "..."
                    header = Text()
                    header.append(f"[{i}] ", style="bold cyan")
                    header.append(str(r.get("source", "")), style="bold")
                    header.append("  Score: ", style="dim")
                    header.append(f"{float(r.get('score', 0.0)):.2%}", style="bold")
                    header.append("  Instance: ", style="dim")
                    header.append(str(r.get("instance", "")), style="italic")
                    console.print(
                        Panel(text, title=header, border_style="dim", padding=(0, 1))
                    )
                _maybe_print_ai_hint()
                return

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
                if response.scan is not None:
                    import dataclasses

                    output["scan"] = [dataclasses.asdict(s) for s in response.scan]
                if response.absence is not None:
                    import dataclasses

                    output["absence"] = [
                        dataclasses.asdict(a) for a in response.absence
                    ]
                if response.timeline is not None:
                    import dataclasses

                    output["timeline"] = [
                        dataclasses.asdict(t) for t in response.timeline
                    ]
                blocked = getattr(response, "index_blocked", None)
                if blocked is not None:
                    output["index_blocked"] = blocked
                click.echo(json.dumps(output, indent=2))
                return

            # Paused-indexing advisory (every mode) — the index may be stale.
            blocked = getattr(response, "index_blocked", None)
            if blocked:
                _tok = blocked.get("estimated_tokens")
                _cap = blocked.get("limit")
                _nums = (
                    f" (~{_tok:,} tokens, cap {_cap:,})"
                    if isinstance(_tok, int) and isinstance(_cap, int)
                    else ""
                )
                console.print(
                    f"[yellow]⚠ Indexing paused{_nums} — results may be stale. "
                    f"Approve: brainpalace jobs {blocked.get('job_id')} --approve[/]"
                )

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

            # Scan mode: print term-count rows as label: value lines
            if response.scan is not None:
                console.print(
                    f"\n[bold]Query:[/] {query_text}\n"
                    f"[dim]Scan results in {response.query_time_ms:.1f}ms[/]\n"
                )
                if not response.scan:
                    console.print(
                        "[yellow]No scan results (archive off, or the term "
                        "never appears).[/]"
                    )
                else:
                    for scan_row in response.scan:
                        console.print(f"{scan_row.label}: {scan_row.value:g}")
                _maybe_print_ai_hint()
                return

            # Absence mode: print "in X, not Y" lines
            if response.absence is not None:
                console.print(
                    f"\n[bold]Query:[/] {query_text}\n"
                    f"[dim]Absence results in {response.query_time_ms:.1f}ms[/]\n"
                )
                if not response.absence:
                    console.print(
                        "[yellow]No gaps found (no two stored values resolved, "
                        "or nothing is absent).[/]"
                    )
                else:
                    for absence_row in response.absence:
                        console.print(
                            f"{absence_row.label}  (in {absence_row.present_in}, "
                            f"not {absence_row.absent_from})"
                        )
                _maybe_print_ai_hint()
                return

            # Timeline mode: print entity edge-validity history lines
            if response.timeline is not None:
                if not response.timeline:
                    # M3: empty has two causes — no entity parsed from the query,
                    # or the entity resolved to no node / no edges. Cover both.
                    console.print(
                        "[yellow]No history found — the query named no "
                        "recognizable entity, or the entity resolved to no graph "
                        "node / has no edges. Try 'history of <name>'.[/]"
                    )
                else:
                    for tl_row in response.timeline:
                        mark = "[green]✓[/]" if tl_row.valid else "[dim]✗[/]"
                        until = tl_row.valid_until or "now"
                        console.print(
                            f"{mark} {tl_row.subject} —{tl_row.predicate}→ "
                            f"{tl_row.object}  [{tl_row.valid_from or '?'} … {until}]"
                        )
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
