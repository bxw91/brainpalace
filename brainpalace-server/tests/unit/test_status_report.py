from brainpalace_server.status_report import build_status_report


def _rows(report):
    return {r.key: r for r in report.rows}


def test_core_rows_present_and_neutral():
    data = {
        "total_documents": 1361,
        "code_documents": 1150,
        "doc_documents": 211,
        "total_chunks": 11769,
        "total_code_chunks": 8115,
        "total_doc_chunks": 1252,
        "indexing_in_progress": False,
        "indexed_folders": ["/a", "/b"],
        "last_indexed_at": "2026-07-22T10:00:00Z",
        "features": {},
    }
    r = _rows(
        build_status_report(
            data, bm25={"language": "en", "engine": "stem"}, version="26.7.10"
        )
    )
    assert r["server_version"].value == "26.7.10"
    assert r["total_documents"].value == "1361 (1150 code · 211 docs)"
    assert r["total_chunks"].value == "11769 (8115 code · 1252 docs)"
    assert r["indexing"].value == "Idle" and r["indexing"].tone == "good"
    assert r["bm25_language"].value == "en (engine: stem)"


def test_feature_rows_tone_and_wording():
    data = {
        "total_documents": 1,
        "total_chunks": 1,
        "text_ingest": {"chunks": 5},
        "features": {
            "session_archive": {
                "enabled": True,
                "archived_files": 1046,
                "archived_bytes": 607_600_000,
                "retain_days": 0,
                "tools": ["claude-code", "codex"],
                "pending_summarization": 330,
            },
            "session_memory": {
                "enabled": True,
                "watcher_running": True,
                "session_chunks": 12,
                "curated_memories": 3,
                "memory_cap_pressure": {"skipped": 2},
            },
            "graph_index": {
                "enabled": True,
                "store_type": "sqlite",
                "entity_count": 10,
                "relationship_count": 5,
            },
            "git_index": {"enabled": False},
            "read_only": True,
        },
    }
    r = {row.key: row for row in build_status_report(data, bm25={}, version="v").rows}
    assert (
        r["session_archive"].tone == "good"
        and "1,046 files" in r["session_archive"].value
    )
    assert r["session_tools"].value == "claude-code, codex"
    assert r["session_queue"].tone == "warn" and "330" in r["session_queue"].value
    assert (
        r["session_memory"].tone == "warn"
        and "cap pressure" in r["session_memory"].value
    )
    assert r["text_ingest"].tone == "good" and "5" in r["text_ingest"].value
    assert r["graph_index"].tone == "good" and "10 entities" in r["graph_index"].value
    assert r["git_index"].tone == "dim"
    assert r["read_only"].tone == "bad"
    assert all(
        "[" not in row.value
        for row in build_status_report(data, bm25={}, version="v").rows
    )


def test_alerts_drift_and_paused_only():
    data = {
        "total_documents": 0,
        "total_chunks": 0,
        "index_warnings": ["embedding model changed"],
        "features": {
            "blocked_jobs": {
                "count": 1,
                "latest": {"job_id": "j1", "estimated_tokens": 120000, "limit": 100000},
            },
            "read_only": True,
            "self_heal": {"last": {"error": True, "restored": 1, "recoverable": 2}},
        },
    }
    report = build_status_report(data, bm25={}, version="v")
    kinds = {a.kind for a in report.alerts}
    assert kinds == {"index_drift", "indexing_paused"}  # NOT read_only/self_heal
    paused = next(a for a in report.alerts if a.kind == "indexing_paused")
    assert paused.action and "j1" in paused.action
