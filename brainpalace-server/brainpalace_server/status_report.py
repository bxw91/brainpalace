"""Presentation-neutral status report — the single source of the `bp status`
lines, rendered by BOTH the CLI table and the dashboard Status tab. Values carry
NO Rich/HTML markup; severity travels as `tone`/`severity`. Add a row here → it
appears in both surfaces automatically."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Tone = Literal["default", "good", "warn", "bad", "dim", "accent"]
Severity = Literal["info", "warn", "bad"]


class StatusRow(BaseModel):
    key: str
    label: str
    value: str
    tone: Tone = "default"


class StatusAlert(BaseModel):
    kind: str
    severity: Severity
    title: str
    lines: list[str]
    action: str | None = None


class StatusReport(BaseModel):
    rows: list[StatusRow]
    alerts: list[StatusAlert]


# Canonical reason the server records when stage-2 is skipped *because* the
# server is read-only (set in startup_reconcile.self_heal_on_startup). Matching
# it lets status distinguish the intentional skip from a genuine incomplete
# recovery. Keep in sync with the server literal.
_READ_ONLY_SKIP_REASON = "read-only mode"


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def build_status_report(
    data: dict[str, Any], *, bm25: dict[str, str], version: str
) -> StatusReport:
    rows: list[StatusRow] = []
    alerts: list[StatusAlert] = []

    rows.append(StatusRow(key="server_version", label="Server Version", value=version))
    rows.append(
        StatusRow(
            key="total_documents",
            label="Total Documents",
            value=f"{_int(data.get('total_documents'))} "
            f"({_int(data.get('code_documents'))} code · "
            f"{_int(data.get('doc_documents'))} docs)",
        )
    )
    rows.append(
        StatusRow(
            key="total_chunks",
            label="Total Chunks",
            value=f"{_int(data.get('total_chunks'))} "
            f"({_int(data.get('total_code_chunks'))} code · "
            f"{_int(data.get('total_doc_chunks'))} docs)",
        )
    )
    if data.get("indexing_in_progress"):
        rows.append(
            StatusRow(
                key="indexing",
                label="Indexing Progress",
                value=f"{float(data.get('progress_percent') or 0.0):.1f}%",
                tone="warn",
            )
        )
        if data.get("current_job_id"):
            rows.append(
                StatusRow(
                    key="current_job",
                    label="Current Job",
                    value=str(data["current_job_id"]),
                )
            )
    else:
        rows.append(
            StatusRow(key="indexing", label="Indexing", value="Idle", tone="good")
        )

    folders = data.get("indexed_folders") or []
    if folders:
        shown = "\n".join(folders[:5]) + (
            f"\n... and {len(folders) - 5} more" if len(folders) > 5 else ""
        )
        rows.append(
            StatusRow(key="indexed_folders", label="Indexed Folders", value=shown)
        )
    if data.get("last_indexed_at"):
        rows.append(
            StatusRow(
                key="last_indexed",
                label="Last Indexed",
                value=str(data["last_indexed_at"]),
            )
        )

    _append_feature_rows(rows, data)  # Task 2
    _append_alerts(alerts, data, data.get("features") or {})  # Task 3

    if bm25:
        rows.append(
            StatusRow(
                key="bm25_language",
                label="BM25 Language",
                value=f"{bm25.get('language', 'en')} "
                f"(engine: {bm25.get('engine', 'stem')})",
            )
        )
    return StatusReport(rows=rows, alerts=alerts)


def _append_feature_rows(rows: list[StatusRow], data: dict[str, Any]) -> None:
    """Port every feature/conditional row from `bp status` (status.py),
    same order + predicates, Rich markup -> tone."""
    features = data.get("features") or {}

    # File watcher — feature view (clearer 0-folder state than the legacy
    # top-level field).
    fw = features.get("file_watcher")
    if isinstance(fw, dict):
        watched = _int(fw.get("watched_folders"))
        if fw.get("enabled") and watched == 0:
            rows.append(
                StatusRow(
                    key="file_watcher",
                    label="File Watcher",
                    value="running (0 folders — none marked watch=auto)",
                    tone="warn",
                )
            )
        elif fw.get("enabled"):
            rows.append(
                StatusRow(
                    key="file_watcher",
                    label="File Watcher",
                    value=f"running ({watched} watched folder(s))",
                )
            )
        else:
            rows.append(
                StatusRow(key="file_watcher", label="File Watcher", value="stopped")
            )

    # Session archive (raw transcript backup) — independent of index.
    arch = features.get("session_archive")
    if isinstance(arch, dict):
        if arch.get("enabled"):
            files = _int(arch.get("archived_files"))
            size_mb = _int(arch.get("archived_bytes")) / (1024 * 1024)
            retain = _int(arch.get("retain_days"))
            window = "forever" if retain <= 0 else f"{retain}d"
            rows.append(
                StatusRow(
                    key="session_archive",
                    label="Session Archive",
                    value=f"on — {files:,} files, {size_mb:.1f} MB ({window})",
                    tone="good",
                )
            )
            tools = arch.get("tools") or []
            rows.append(
                StatusRow(
                    key="session_tools",
                    label="Session Tools",
                    value=", ".join(tools) if tools else "none detected",
                    tone="default" if tools else "dim",
                )
            )
            pending = _int(arch.get("pending_summarization"))
            rows.append(
                StatusRow(
                    key="session_queue",
                    label="Session Queue",
                    value=(
                        f"{pending:,} pending (un-summarized; "
                        f"drains when extraction.mode is subagent/auto)"
                        if pending
                        else "0 — empty"
                    ),
                    tone="warn" if pending else "dim",
                )
            )
        else:
            rows.append(
                StatusRow(
                    key="session_archive",
                    label="Session Archive",
                    value="off (SESSION_ARCHIVE_ENABLED=false)",
                    tone="dim",
                )
            )

    # Session memory / INDEX (embeddings).
    mem = features.get("session_memory")
    if isinstance(mem, dict):
        if mem.get("enabled"):
            state = "watching" if mem.get("watcher_running") else "idle"
            cap = _int(mem.get("memory_char_cap"))
            caps = f", {_int(mem.get('memory_char_count'))}/{cap} chars" if cap else ""
            pressure = mem.get("memory_cap_pressure")
            val = (
                f"on ({state}) — {_int(mem.get('session_chunks')):,} session chunks, "
                f"{_int(mem.get('curated_memories')):,} curated{caps}"
            )
            tone: Tone = "good"
            if pressure:
                val += (
                    f" · ⚠ cap pressure — {_int(pressure.get('skipped'))} "
                    f"promotions skipped (curate memory)"
                )
                tone = "warn"
            rows.append(
                StatusRow(
                    key="session_memory", label="Session Memory", value=val, tone=tone
                )
            )
        else:
            rows.append(
                StatusRow(
                    key="session_memory",
                    label="Session Memory",
                    value="off (enable: brainpalace init --sessions)",
                    tone="dim",
                )
            )

    # Session summarization (free; independent of Session Memory/Archive).
    extract = features.get("session_extraction")
    if isinstance(extract, dict):
        mode = str(extract.get("mode", "off"))
        if mode == "off":
            rows.append(
                StatusRow(
                    key="session_summarization",
                    label="Session Summarization",
                    value="off (free; enable: brainpalace init)",
                    tone="dim",
                )
            )
        else:
            done = _int(extract.get("summarized_sessions"))
            total = _int(extract.get("total_sessions"))
            pct = float(extract.get("summarized_pct") or 0.0)
            if total:
                rows.append(
                    StatusRow(
                        key="session_summarization",
                        label="Session Summarization",
                        value=f"{pct:.0f}% summarized "
                        f"({done:,}/{total:,} sessions, mode: {mode})",
                        tone="good",
                    )
                )
            else:
                rows.append(
                    StatusRow(
                        key="session_summarization",
                        label="Session Summarization",
                        value=f"no sessions yet (mode: {mode})",
                        tone="dim",
                    )
                )

    # Session recall in search — what session-derived data the query path
    # will surface.
    sess_feat = features.get("session_memory")
    ext_feat = features.get("session_extraction")
    if isinstance(sess_feat, dict) or isinstance(ext_feat, dict):
        vector_on = bool(isinstance(sess_feat, dict) and sess_feat.get("enabled"))
        summ_on = (
            isinstance(ext_feat, dict) and str(ext_feat.get("mode", "off")) != "off"
        )
        v_txt = "on" if vector_on else "off"
        s_txt = "on" if summ_on else "off"
        suffix = "" if vector_on and summ_on else " — disabled data hidden"
        rows.append(
            StatusRow(
                key="session_recall",
                label="Session Recall",
                value=f"vectors {v_txt}, summaries {s_txt}{suffix}",
            )
        )

    # Doc-trust ranking weight.
    ranking = features.get("ranking")
    if isinstance(ranking, dict):
        doc_weight = float(ranking.get("doc_weight", 0.5))
        note = "docs ranked below code" if doc_weight < 1.0 else "docs equal to code"
        rows.append(
            StatusRow(
                key="doc_trust_weight",
                label="Doc Trust Weight",
                value=f"{doc_weight:g} ({note})",
            )
        )

    # Embedding cache status — top-level field (Phase 16), not under features.
    embedding_cache = data.get("embedding_cache")
    if embedding_cache:
        entry_count = _int(embedding_cache.get("entry_count"))
        hit_rate = float(embedding_cache.get("hit_rate") or 0.0)
        hits = _int(embedding_cache.get("hits"))
        misses = _int(embedding_cache.get("misses"))
        rows.append(
            StatusRow(
                key="embedding_cache",
                label="Embedding Cache",
                value=f"{entry_count:,} entries, {hit_rate:.1%} hit rate "
                f"({hits:,} hits, {misses:,} misses)",
            )
        )

    # Graph index status.
    graph_status = features.get("graph_index")
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
            graph_note = f"Enabled ({store_note}) - {entities} entities, {rels} rels"
            if graph_status.get("needs_identity_rebuild"):
                graph_note += " — one-time rebuild pending (runs on next index)"
            rows.append(
                StatusRow(
                    key="graph_index",
                    label="Graph Index",
                    value=graph_note,
                    tone="good",
                )
            )
        else:
            rows.append(
                StatusRow(
                    key="graph_index", label="Graph Index", value="Disabled", tone="dim"
                )
            )

    # Programmatic text-ingest chunks — read from `data`, not `features`.
    if _int((data.get("text_ingest") or {}).get("chunks")) > 0:
        rows.append(
            StatusRow(
                key="text_ingest",
                label="Text Ingest",
                value=f"{_int(data['text_ingest']['chunks']):,} chunks",
                tone="good",
            )
        )

    # Doc-graph extraction — always shown when the feature block is present.
    dge = features.get("doc_graph_extraction")
    if isinstance(dge, dict):
        state = str(dge.get("state", "off"))
        pending = _int(dge.get("pending"))
        ungraphed = bool(dge.get("ungraphed", False))
        provider = dge.get("provider")
        if state == "off":
            val = "off"
            if ungraphed:
                val += (
                    f" — {pending:,} un-graphed "
                    f"(extraction off; enable with extraction.mode)"
                )
            rows.append(
                StatusRow(
                    key="doc_graph_extraction",
                    label="Doc Graph Extraction",
                    value=val,
                    tone="dim",
                )
            )
        elif state == "subagent":
            suffix = f" — {pending:,} pending" if pending else ""
            rows.append(
                StatusRow(
                    key="doc_graph_extraction",
                    label="Doc Graph Extraction",
                    value=f"on (subagent){suffix}",
                    tone="good",
                )
            )
        elif state == "provider":
            label = f": {provider}" if provider else ""
            suffix = f" — {pending:,} pending" if pending else ""
            rows.append(
                StatusRow(
                    key="doc_graph_extraction",
                    label="Doc Graph Extraction",
                    value=f"on (provider{label}){suffix}",
                    tone="good",
                )
            )
        else:  # unavailable
            rows.append(
                StatusRow(
                    key="doc_graph_extraction",
                    label="Doc Graph Extraction",
                    value="unavailable — provider mode, no provider/lock "
                    "(set EXTRACTION_PROVIDER_ENABLED=true)",
                    tone="warn",
                )
            )

    # Records / compute feature block.
    rec = features.get("records")
    if isinstance(rec, dict):
        total_rec = _int(rec.get("total"))
        unverified_rec = _int(rec.get("unverified"))
        metrics_rec = rec.get("metrics") or []
        metrics_str = ", ".join(str(m) for m in metrics_rec) if metrics_rec else "none"
        rows.append(
            StatusRow(
                key="records_compute",
                label="Records / Compute",
                value=f"{total_rec:,} ({unverified_rec:,} unverified) "
                f"· metrics: {metrics_str}",
            )
        )

    # LSP cross-references.
    lsp_feat = features.get("lsp")
    if isinstance(lsp_feat, dict):
        if lsp_feat.get("enabled"):
            langs = ", ".join(lsp_feat.get("active") or []) or "—"
            rows.append(
                StatusRow(
                    key="lsp", label="LSP", value=f"active ({langs})", tone="good"
                )
            )
        elif lsp_feat.get("detected"):
            det = ", ".join(lsp_feat.get("detected") or [])
            rows.append(
                StatusRow(
                    key="lsp", label="LSP", value=f"idle — detected {det}", tone="warn"
                )
            )
        else:
            configured = lsp_feat.get("configured") or []
            if configured:
                langs = ", ".join(configured)
                rows.append(
                    StatusRow(
                        key="lsp",
                        label="LSP",
                        value=f"not installed for {langs} — "
                        f"run brainpalace lsp install",
                        tone="warn",
                    )
                )
            else:
                rows.append(
                    StatusRow(
                        key="lsp",
                        label="LSP",
                        value="not found — install pyright for exact call edges",
                        tone="dim",
                    )
                )

    # Git history index.
    git_idx = features.get("git_index")
    if isinstance(git_idx, dict):
        if git_idx.get("enabled"):
            commits = _int(git_idx.get("commit_count"))
            rows.append(
                StatusRow(
                    key="git_index",
                    label="Git Index",
                    value=f"on — {commits:,} commits",
                    tone="good",
                )
            )
        else:
            rows.append(
                StatusRow(
                    key="git_index",
                    label="Git Index",
                    value="off (enable: brainpalace init --git-history)",
                    tone="dim",
                )
            )

    # Reference catalog — shown only when references exist.
    refs = features.get("references")
    if isinstance(refs, dict) and refs.get("enabled"):
        ref_total = _int(refs.get("total"))
        if ref_total > 0:
            ref_unembedded = _int(refs.get("unembedded"))
            rows.append(
                StatusRow(
                    key="references",
                    label="References",
                    value=f"{ref_total:,} ({ref_unembedded:,} unembedded)",
                    tone="good",
                )
            )

    # Index health: self-heal audit — only a row when a heal actually shed
    # vectors; a clean index stays quiet.
    index_health = features.get("index_health")
    if isinstance(index_health, dict):
        heal_events = _int(index_health.get("heal_events"))
        dropped = _int(index_health.get("total_dropped"))
        if heal_events and dropped:
            rows.append(
                StatusRow(
                    key="index_health",
                    label="Index Health",
                    value=f"⚠ {heal_events} heal event(s), ~{dropped:,} vectors shed — "
                    f"see .brainpalace/heal-events.jsonl; re-index to recover "
                    f"(brainpalace index . --force)",
                    tone="warn",
                )
            )

    # Read-only mode banner (master provider kill switch).
    if features.get("read_only"):
        rows.append(
            StatusRow(
                key="read_only",
                label="Read-Only",
                value="ON — provider calls disabled (embedding/summarization/"
                "remote-rerank off; vector queries → BM25; indexing skipped)",
                tone="bad",
            )
        )

    # Self-heal recovery (lost chunks restored from cache+dead at start).
    self_heal = features.get("self_heal")
    if isinstance(self_heal, dict):
        last = self_heal.get("last")
        if isinstance(last, dict):
            restored = _int(last.get("restored"))
            recoverable = _int(last.get("recoverable"))
            reason = last.get("incomplete_reason")
            if last.get("error"):
                rows.append(
                    StatusRow(
                        key="self_heal",
                        label="Self-Heal",
                        value=f"⚠ INCOMPLETE — restored {restored:,}/{recoverable:,}; "
                        f"stage 2 skipped to protect data — fix + restart",
                        tone="bad",
                    )
                )
            elif reason == _READ_ONLY_SKIP_REASON:
                rows.append(
                    StatusRow(
                        key="self_heal",
                        label="Self-Heal",
                        value=f"recovered {restored:,}/{recoverable:,} chunk(s) from "
                        f"cache+dead (no re-embed); stage 2 skipped — "
                        f"read-only (no deletes)",
                        tone="good",
                    )
                )
            elif reason:
                rows.append(
                    StatusRow(
                        key="self_heal",
                        label="Self-Heal",
                        value=f"⚠ INCOMPLETE — restored {restored:,}/{recoverable:,}; "
                        f"stage 2 skipped to protect data — fix + restart",
                        tone="bad",
                    )
                )
            else:
                dropped_f = _int(last.get("files_dropped"))
                residue = _int(last.get("residue"))
                rows.append(
                    StatusRow(
                        key="self_heal",
                        label="Self-Heal",
                        value=f"restored {restored:,} chunk(s) from cache+dead "
                        f"(no re-embed); {dropped_f:,} file(s) re-indexing "
                        f"({residue:,} chunk(s) need re-embed)",
                        tone="good",
                    )
                )


def _append_alerts(
    alerts: list[StatusAlert], data: dict[str, Any], features: dict[str, Any]
) -> None:
    warnings = [str(w) for w in (data.get("index_warnings") or []) if w]
    if warnings:
        alerts.append(
            StatusAlert(
                kind="index_drift", severity="warn", title="Index drift", lines=warnings
            )
        )

    bj = features.get("blocked_jobs") or {}
    count = _int(bj.get("count"))
    if count > 0:
        latest = bj.get("latest") or {}
        job_id = latest.get("job_id", "?")
        tokens, limit = latest.get("estimated_tokens"), latest.get("limit")
        nums = (
            f" — needs ~{tokens:,} embedding tokens (cap {limit:,})"
            if isinstance(tokens, int) and isinstance(limit, int)
            else ""
        )
        more = f" (+{count - 1} more blocked)" if count > 1 else ""
        alerts.append(
            StatusAlert(
                kind="indexing_paused",
                severity="warn",
                title="Indexing paused",
                lines=[f"Indexing paused{nums}{more}. Nothing was spent."],
                action=f"brainpalace jobs {job_id} --approve",
            )
        )
