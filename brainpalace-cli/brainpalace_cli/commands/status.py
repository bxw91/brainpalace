"""Status command for checking server health."""

from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..client import (
    ConnectionError,
    DocServeClient,
    ServerError,
    exit_on_connection_error,
)
from ..config import get_server_url
from ._dashboard_url import dashboard_status_info, render_dashboard_status

console = Console()


def _load_bm25_config_for_status() -> dict[str, str]:
    """Load BM25 language/engine from the project config.yaml, if available.

    Returns a dict with 'language' and 'engine' keys, or an empty dict when
    no config.yaml is found (e.g. status run outside an initialized project).
    """
    try:
        from brainpalace_server.config.bm25_config import load_bm25_config

        cfg = load_bm25_config()
        return {"language": cfg.language, "engine": cfg.engine}
    except Exception:  # noqa: BLE001
        return {}


def _read_only_row(features: dict[str, Any]) -> tuple[str, str] | None:
    """Return the (label, value) status row when read-only is active, else None."""
    if features.get("read_only"):
        return (
            "Read-Only",
            "[red]ON[/] — provider calls disabled (embedding/summarization/"
            "remote-rerank off; vector queries → BM25; indexing skipped)",
        )
    return None


# Canonical reason the server records when stage-2 is skipped *because* the
# server is read-only (set in startup_reconcile.self_heal_on_startup). Matching
# it lets status distinguish the intentional skip from a genuine incomplete
# recovery. Keep in sync with the server literal.
_READ_ONLY_SKIP_REASON = "read-only mode"


def _self_heal_row(features: dict[str, Any]) -> tuple[str, str] | None:
    """Return the (label, value) row for the last self-heal recovery, else None.

    Distinguishes three outcomes so a healthy run is never shown as a problem:
      * genuine failure/incomplete recovery → red ``⚠ INCOMPLETE … fix + restart``
      * intentional read-only stage-2 skip (recovery succeeded, nothing deleted)
        → green ``recovered X/Y … stage 2 skipped — read-only (no deletes)``
      * complete recovery → green ``restored X … N re-indexing … M need re-index``
    """
    self_heal = features.get("self_heal")
    if not isinstance(self_heal, dict):
        return None
    last = self_heal.get("last")
    if not isinstance(last, dict):
        return None

    restored = int(last.get("restored", 0) or 0)
    recoverable = int(last.get("recoverable", 0) or 0)
    reason = last.get("incomplete_reason")

    if last.get("error"):
        return (
            "Self-Heal",
            f"[red]⚠ INCOMPLETE[/] — restored {restored:,}/{recoverable:,}; "
            f"stage 2 skipped to protect data — fix + restart",
        )
    if reason == _READ_ONLY_SKIP_REASON:
        return (
            "Self-Heal",
            f"[green]recovered {restored:,}/{recoverable:,} chunk(s)[/] from "
            f"cache+dead (no re-embed); stage 2 skipped — read-only (no deletes)",
        )
    if reason:
        return (
            "Self-Heal",
            f"[red]⚠ INCOMPLETE[/] — restored {restored:,}/{recoverable:,}; "
            f"stage 2 skipped to protect data — fix + restart",
        )
    dropped_f = int(last.get("files_dropped", 0) or 0)
    residue = int(last.get("residue", 0) or 0)
    return (
        "Self-Heal",
        f"[green]restored {restored:,} chunk(s)[/] from cache+dead (no re-embed); "
        f"{dropped_f:,} file(s) re-indexing ({residue:,} chunk(s) need re-embed)",
    )


def _status_all(json_output: bool) -> None:
    """Show detailed status for every running registered server (B2b)."""
    import json

    from .list_cmd import scan_instances

    instances = [i for i in scan_instances() if i.get("status") == "running"]
    servers: list[dict[str, Any]] = []
    for inst in instances:
        base_url = str(inst.get("base_url", ""))
        if not base_url:
            continue
        try:
            with DocServeClient(base_url=base_url) as client:
                health = client.health()
                indexing = client.status()
        except (ConnectionError, ServerError):
            continue  # Server vanished between registry scan and probe.
        watcher = indexing.file_watcher or {}
        servers.append(
            {
                "project_root": inst.get("project_root", ""),
                "base_url": base_url,
                "pid": inst.get("pid", 0),
                "health": health.status,
                "version": health.version,
                "total_documents": indexing.total_documents,
                "total_chunks": indexing.total_chunks,
                "watcher_running": bool(watcher.get("running", False)),
                "watched_folders": int(watcher.get("watched_folders", 0)),
                "last_indexed_at": indexing.last_indexed_at,
            }
        )

    if json_output:
        click.echo(json.dumps({"servers": servers, "total": len(servers)}, indent=2))
        return

    if not servers:
        console.print("[dim]No running BrainPalace servers found.[/]")
        console.print("\n[dim]Start a server with: brainpalace start[/]")
        return

    for srv in servers:
        if srv["watcher_running"]:
            watcher_txt = f"running ({srv['watched_folders']} folder(s))"
        else:
            watcher_txt = "stopped"
        last_indexed = srv["last_indexed_at"] or "never"
        body = (
            f"[bold]URL:[/] {srv['base_url']}\n"
            f"[bold]PID:[/] {srv['pid']}\n"
            f"[bold]Health:[/] {srv['health']}\n"
            f"[bold]Chunks:[/] {srv['total_chunks']:,} "
            f"({srv['total_documents']:,} documents)\n"
            f"[bold]Watcher:[/] {watcher_txt}\n"
            f"[bold]Last indexed:[/] {last_indexed}"
        )
        console.print(Panel(body, title=str(srv["project_root"]), border_style="cyan"))

    console.print(f"\n[dim]{len(servers)} running server(s).[/]")


@click.command("status")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="BrainPalace server URL (default: from config or http://127.0.0.1:8000)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show additional detail")
@click.option(
    "--all",
    "-a",
    "show_all",
    is_flag=True,
    help="Show detailed status for every running registered server",
)
def status_command(
    url: str | None, json_output: bool, verbose: bool, show_all: bool
) -> None:
    """Check BrainPalace server status and health."""
    if show_all:
        _status_all(json_output)
        return
    resolved_url = url or get_server_url()
    bm25_cfg = _load_bm25_config_for_status()
    try:
        with DocServeClient(base_url=resolved_url) as client:
            health = client.health()
            indexing = client.status()

            if json_output:
                import json

                output: dict[str, Any] = {
                    "health": {
                        "status": health.status,
                        "message": health.message,
                        "version": health.version,
                        "url": resolved_url,
                    },
                    "dashboard": dashboard_status_info(),
                    "indexing": {
                        "total_documents": indexing.total_documents,
                        "total_chunks": indexing.total_chunks,
                        "indexing_in_progress": indexing.indexing_in_progress,
                        "progress_percent": indexing.progress_percent,
                        "indexed_folders": indexing.indexed_folders,
                        "file_watcher": indexing.file_watcher
                        or {"running": False, "watched_folders": 0},
                        "embedding_cache": indexing.embedding_cache,
                        "features": getattr(indexing, "features", None),
                        "graph_index": getattr(indexing, "graph_index", None),
                        "index_warnings": indexing.index_warnings,
                    },
                }
                if bm25_cfg:
                    output["bm25"] = bm25_cfg
                click.echo(json.dumps(output, indent=2))
                return

            # Determine status color
            status_color = {
                "healthy": "green",
                "indexing": "yellow",
                "degraded": "orange3",
                "unhealthy": "red",
            }.get(health.status, "white")

            # Create status panel
            status_text = f"[bold {status_color}]{health.status.upper()}[/]"
            if health.message:
                status_text += f"\n{health.message}"
            status_text += f"\n[bold]URL:[/] [link={resolved_url}]{resolved_url}[/link]"

            console.print(
                Panel(status_text, title="Server Status", border_style=status_color)
            )

            # Index-drift warnings: a config change (embedding provider/model or
            # storage backend) no longer matches what the existing index was built
            # with. Loud panel so it is not missed.
            if indexing.index_warnings:
                warn_body = "\n".join(f"• {w}" for w in indexing.index_warnings)
                console.print(
                    Panel(
                        warn_body,
                        title="⚠ Index drift",
                        border_style="yellow",
                    )
                )

            # Create info table
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Metric", style="dim")
            table.add_column("Value")

            table.add_row("Server Version", health.version)
            table.add_row(
                "Total Documents",
                f"{indexing.total_documents} "
                f"({indexing.code_documents} code · {indexing.doc_documents} docs)",
            )
            table.add_row(
                "Total Chunks",
                f"{indexing.total_chunks} "
                f"({indexing.code_chunks} code · {indexing.doc_chunks} docs)",
            )

            if indexing.indexing_in_progress:
                table.add_row(
                    "Indexing Progress", f"[yellow]{indexing.progress_percent:.1f}%[/]"
                )
                if indexing.current_job_id:
                    table.add_row("Current Job", indexing.current_job_id)
            else:
                table.add_row("Indexing", "[green]Idle[/]")

            if indexing.indexed_folders:
                table.add_row(
                    "Indexed Folders",
                    "\n".join(indexing.indexed_folders[:5])
                    + (
                        f"\n... and {len(indexing.indexed_folders) - 5} more"
                        if len(indexing.indexed_folders) > 5
                        else ""
                    ),
                )

            if indexing.last_indexed_at:
                table.add_row("Last Indexed", indexing.last_indexed_at)

            features = getattr(indexing, "features", None) or {}

            # File watcher — prefer the consolidated feature view (clearer
            # 0-folder state), fall back to the legacy top-level field.
            fw_feat = features.get("file_watcher")
            if isinstance(fw_feat, dict):
                enabled = bool(fw_feat.get("enabled"))
                watched = int(fw_feat.get("watched_folders", 0) or 0)
                if enabled and watched == 0:
                    table.add_row(
                        "File Watcher",
                        "running ([yellow]0 folders — none marked watch=auto[/])",
                    )
                elif enabled:
                    table.add_row(
                        "File Watcher", f"running ({watched} watched folder(s))"
                    )
                else:
                    table.add_row("File Watcher", "stopped")
            else:
                file_watcher = indexing.file_watcher or {}
                if file_watcher:
                    running = bool(file_watcher.get("running", False))
                    watched_folders = int(file_watcher.get("watched_folders", 0))
                    watcher_status = "running" if running else "stopped"
                    table.add_row(
                        "File Watcher",
                        f"{watcher_status} ({watched_folders} watched folder(s))",
                    )

            # Session archive (raw transcript backup) — independent of index.
            arch = features.get("session_archive")
            if isinstance(arch, dict):
                if arch.get("enabled"):
                    files = int(arch.get("archived_files", 0) or 0)
                    size_mb = int(arch.get("archived_bytes", 0) or 0) / (1024 * 1024)
                    retain = int(arch.get("retain_days", 0) or 0)
                    window = "forever" if retain <= 0 else f"{retain}d"
                    table.add_row(
                        "Session Archive",
                        f"[green]on[/] — {files:,} files, {size_mb:.1f} MB ({window})",
                    )
                else:
                    table.add_row(
                        "Session Archive",
                        "[dim]off[/] (SESSION_ARCHIVE_ENABLED=false)",
                    )

            # Session memory / INDEX (from the feature view).
            sess = features.get("session_memory")
            if isinstance(sess, dict):
                if sess.get("enabled"):
                    sess_state = "watching" if sess.get("watcher_running") else "idle"
                    table.add_row(
                        "Session Memory",
                        f"[green]on[/] ({sess_state}) — "
                        f"{int(sess.get('session_chunks', 0) or 0):,} session "
                        f"chunks, {int(sess.get('curated_memories', 0) or 0):,} "
                        f"curated",
                    )
                else:
                    table.add_row(
                        "Session Memory",
                        "[dim]off[/] (enable: brainpalace init --sessions)",
                    )

            # Session summarization — distillation of transcripts (free, runs
            # via the Claude Code subagent); independent of embedding/index.
            # Always shown so the capability is visible even when off — it is a
            # separate switch from Session Memory (embedding) and Session
            # Archive (raw backup).
            extract = features.get("session_extraction")
            if isinstance(extract, dict):
                mode = str(extract.get("mode", "off"))
                if mode == "off":
                    table.add_row(
                        "Session Summarization",
                        "[dim]off[/] (free; enable: brainpalace init)",
                    )
                else:
                    done = int(extract.get("summarized_sessions", 0) or 0)
                    total = int(extract.get("total_sessions", 0) or 0)
                    pct = float(extract.get("summarized_pct", 0.0) or 0.0)
                    if total:
                        table.add_row(
                            "Session Summarization",
                            f"[green]{pct:.0f}%[/] summarized "
                            f"({done:,}/{total:,} sessions, mode: {mode})",
                        )
                    else:
                        table.add_row(
                            "Session Summarization",
                            f"[dim]no sessions yet[/] (mode: {mode})",
                        )

            # Session recall in search — what session-derived data the query
            # path will surface. A disabled feature's (possibly stale) data is
            # HARD-hidden from results until re-enabled; manually-saved
            # `brainpalace remember` facts are always recallable.
            sess_feat = features.get("session_memory")
            ext_feat = features.get("session_extraction")
            if isinstance(sess_feat, dict) or isinstance(ext_feat, dict):
                vector_on = bool(
                    isinstance(sess_feat, dict) and sess_feat.get("enabled")
                )
                summ_on = (
                    isinstance(ext_feat, dict)
                    and str(ext_feat.get("mode", "off")) != "off"
                )
                v_txt = "[green]on[/]" if vector_on else "[dim]off[/]"
                s_txt = "[green]on[/]" if summ_on else "[dim]off[/]"
                suffix = "" if vector_on and summ_on else " — disabled data hidden"
                table.add_row(
                    "Session Recall",
                    f"vectors {v_txt}, summaries {s_txt}{suffix}",
                )

            # Show embedding cache status if available (Phase 16)
            embedding_cache = indexing.embedding_cache
            if embedding_cache:
                entry_count = int(embedding_cache.get("entry_count", 0))
                hit_rate = float(embedding_cache.get("hit_rate", 0.0))
                hits = int(embedding_cache.get("hits", 0))
                misses = int(embedding_cache.get("misses", 0))
                table.add_row(
                    "Embedding Cache",
                    f"{entry_count:,} entries, {hit_rate:.1%} hit rate "
                    f"({hits:,} hits, {misses:,} misses)",
                )
                if verbose:
                    mem_entries = int(embedding_cache.get("mem_entries", 0))
                    size_bytes = int(embedding_cache.get("size_bytes", 0))
                    size_mb = size_bytes / (1024 * 1024) if size_bytes else 0.0
                    table.add_row("  Memory Entries", f"{mem_entries:,}")
                    table.add_row("  Cache Size", f"{size_mb:.2f} MB")

            # Show graph index status if available (Feature 113)
            graph_status = getattr(indexing, "graph_index", None)
            if graph_status:
                if graph_status.get("enabled"):
                    entities = graph_status.get("entity_count", 0)
                    rels = graph_status.get("relationship_count", 0)
                    store = str(graph_status.get("store_type", "simple"))
                    if store == "sqlite":
                        store_note = "sqlite, temporal"
                    elif store == "simple":
                        store_note = "simple — no temporal validity"
                    else:
                        store_note = store
                    table.add_row(
                        "Graph Index",
                        f"[green]Enabled[/] ({store_note}) - "
                        f"{entities} entities, {rels} rels",
                    )
                else:
                    table.add_row("Graph Index", "[dim]Disabled[/]")

            lsp = features.get("lsp")
            if isinstance(lsp, dict):
                if lsp.get("enabled"):
                    langs = ", ".join(lsp.get("languages", []) or [])
                    table.add_row("LSP", f"[green]enabled[/] ({langs})")
                else:
                    table.add_row(
                        "LSP", "[dim]disabled[/] (set BRAINPALACE_LSP_LANGUAGES)"
                    )

            git_idx = features.get("git_index")
            if isinstance(git_idx, dict):
                if git_idx.get("enabled"):
                    commits = int(git_idx.get("commit_count", 0) or 0)
                    table.add_row("Git Index", f"[green]on[/] — {commits:,} commits")
                else:
                    table.add_row(
                        "Git Index",
                        "[dim]off[/] (enable: brainpalace init --git-history)",
                    )

            # Index health: self-heal audit (#5). Only show a row when a heal
            # actually shed vectors — a clean index stays quiet.
            index_health = features.get("index_health")
            if isinstance(index_health, dict):
                heal_events = int(index_health.get("heal_events", 0) or 0)
                dropped = int(index_health.get("total_dropped", 0) or 0)
                if heal_events and dropped:
                    table.add_row(
                        "Index Health",
                        f"[yellow]⚠ {heal_events} heal event(s), "
                        f"~{dropped:,} vectors shed[/] — "
                        f"see .brainpalace/heal-events.jsonl; "
                        f"re-index to recover (brainpalace index . --force)",
                    )

            # Read-only mode banner (master provider kill switch) — show first.
            _ro_row = _read_only_row(features)
            if _ro_row is not None:
                table.add_row(*_ro_row)

            # Self-heal recovery (lost chunks restored from cache+dead at start).
            # The read-only stage-2 skip is shown as a healthy outcome, not a
            # scary "INCOMPLETE" — see _self_heal_row.
            sh_row = _self_heal_row(features)
            if sh_row is not None:
                table.add_row(*sh_row)

            # Show BM25 language/engine from local config.yaml (Task 16)
            if bm25_cfg:
                lang = bm25_cfg.get("language", "en")
                engine = bm25_cfg.get("engine", "stem")
                table.add_row("BM25 Language", f"{lang} (engine: {engine})")

            console.print(table)

            # Web dashboard — always show the pink box (running URL or notice).
            render_dashboard_status(console=console)

    except ConnectionError as e:
        # Dashboard is independent of the project server — surface its box even
        # when this server is down (human output only).
        if not json_output:
            render_dashboard_status(console=console)
        exit_on_connection_error(e, base_url=resolved_url, json_output=json_output)

    except ServerError as e:
        if json_output:
            import json

            click.echo(json.dumps({"error": str(e), "detail": e.detail}))
        else:
            console.print(f"[red]Server Error ({e.status_code}):[/] {e.detail}")
        raise SystemExit(1) from e
