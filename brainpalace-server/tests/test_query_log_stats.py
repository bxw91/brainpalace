"""Aggregation tests for QueryLogService.stats (dashboard plan 02)."""

from brainpalace_server.services.query_log import QueryLogService


def _seed(svc: QueryLogService) -> None:
    # 3 hybrid (one zero-result), 1 bm25; latencies 10/20/30/40.
    svc.record(
        query="alpha",
        mode="hybrid",
        top_k=5,
        latency_ms=10.0,
        results=[{"score": 1, "path": "a.py", "snippet": "x"}],
        ts=1000.0,
    )
    svc.record(
        query="alpha",
        mode="hybrid",
        top_k=5,
        latency_ms=20.0,
        results=[{"score": 1, "path": "a.py", "snippet": "x"}],
        ts=1100.0,
    )
    svc.record(
        query="ghost", mode="hybrid", top_k=5, latency_ms=30.0, results=[], ts=1200.0
    )
    svc.record(
        query="beta",
        mode="bm25",
        top_k=5,
        latency_ms=40.0,
        results=[{"score": 1, "path": "b.py", "snippet": "y"}],
        ts=5000.0,
    )


def test_stats_totals_and_modes(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    _seed(svc)
    s = svc.stats()
    assert s["total"] == 4
    assert s["zero_result_count"] == 1
    assert s["mode_distribution"] == {"hybrid": 3, "bm25": 1}


def test_stats_latency_percentiles(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    _seed(svc)
    s = svc.stats()
    assert s["latency"]["p50"] in (20.0, 30.0)  # nearest-rank on 4 values
    assert s["latency"]["p95"] == 40.0
    assert s["latency"]["avg"] == 25.0


def test_stats_top_and_zero_queries(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    _seed(svc)
    s = svc.stats(top_n=2)
    assert s["top_queries"][0]["query"] == "alpha"
    assert s["top_queries"][0]["count"] == 2
    assert len(s["top_queries"]) == 2
    assert s["zero_result_queries"] == [
        {"query": "ghost", "count": 1, "last_ts": 1200.0}
    ]


def test_stats_since_filters(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    _seed(svc)
    s = svc.stats(since=4000.0)
    assert s["total"] == 1
    assert s["mode_distribution"] == {"bm25": 1}


def test_stats_empty_log(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    s = svc.stats()
    assert s["total"] == 0
    assert s["latency"] == {"p50": 0.0, "p95": 0.0, "avg": 0.0}
    assert s["latency_trend"] == []


def test_stats_trend_buckets_hourly(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    _seed(svc)
    s = svc.stats()
    # ts 1000/1100/1200 share an hour bucket; ts 5000 is a second bucket.
    assert len(s["latency_trend"]) == 2
    assert s["latency_trend"][0]["count"] == 3
    assert s["latency_trend"][1]["count"] == 1
