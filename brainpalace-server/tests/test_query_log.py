import time

from brainpalace_server.services.query_log import QueryLogService


def test_insert_and_list(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    svc.record(
        query="hello",
        mode="hybrid",
        top_k=5,
        latency_ms=12.3,
        results=[{"score": 0.9, "path": "a.py", "lines": "1-10", "snippet": "x"}],
        alpha=0.5,
        filters={},
    )
    rows = svc.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["query"] == "hello"
    assert rows[0]["result_count"] == 1
    assert "results" not in rows[0]  # list view omits payload


def test_detail_includes_results(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    qid = svc.record(
        query="q",
        mode="bm25",
        top_k=3,
        latency_ms=1.0,
        results=[{"score": 0.5, "path": "b.py", "lines": "2-3", "snippet": "y"}],
        alpha=0.0,
        filters={},
    )
    detail = svc.get(qid)
    assert detail["results"][0]["path"] == "b.py"


def test_filters_by_mode_and_contains(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    svc.record(
        query="alpha bravo",
        mode="hybrid",
        top_k=5,
        latency_ms=1,
        results=[],
        alpha=0.5,
        filters={},
    )
    svc.record(
        query="charlie",
        mode="bm25",
        top_k=5,
        latency_ms=1,
        results=[],
        alpha=0.0,
        filters={},
    )
    assert len(svc.list_recent(mode="bm25")) == 1
    assert len(svc.list_recent(contains="bravo")) == 1


def test_purge_removes_old(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    old_ts = time.time() - 10 * 86400
    svc.record(
        query="old",
        mode="hybrid",
        top_k=5,
        latency_ms=1,
        results=[],
        alpha=0.5,
        filters={},
        ts=old_ts,
    )
    svc.record(
        query="new",
        mode="hybrid",
        top_k=5,
        latency_ms=1,
        results=[],
        alpha=0.5,
        filters={},
    )
    svc.purge(retention_days=7)
    rows = svc.list_recent()
    assert len(rows) == 1 and rows[0]["query"] == "new"


def test_purge_zero_keeps_forever(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    old_ts = time.time() - 10 * 86400
    svc.record(
        query="old",
        mode="hybrid",
        top_k=5,
        latency_ms=1,
        results=[],
        alpha=0.5,
        filters={},
        ts=old_ts,
    )
    assert svc.purge(retention_days=0) == 0
    assert len(svc.list_recent()) == 1
