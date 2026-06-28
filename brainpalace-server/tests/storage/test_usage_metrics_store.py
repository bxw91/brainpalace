# tests/storage/test_usage_metrics_store.py
from brainpalace_server.storage.usage_metrics_store import UsageMetricsStore


def _store(tmp_path):
    return UsageMetricsStore(tmp_path / "usage.db")


def test_record_increments_on_conflict(tmp_path):
    s = _store(tmp_path)
    s.record(
        100,
        "embedding",
        "openai",
        "text-embedding-3-large",
        "doc",
        chunks=10,
        calls=1,
        tokens_in=500,
    )
    s.record(
        100,
        "embedding",
        "openai",
        "text-embedding-3-large",
        "doc",
        chunks=5,
        calls=1,
        tokens_in=250,
    )
    totals, _ = s.aggregate(since_bucket=0)
    row = next(r for r in totals if r["channel"] == "embedding")
    assert row["chunks"] == 15 and row["calls"] == 2 and row["tokens_in"] == 750


def test_aggregate_totals_and_series_split(tmp_path):
    s = _store(tmp_path)
    s.record(100, "embedding", "openai", "m", "doc", chunks=2, tokens_in=200)
    s.record(
        100,
        "provider",
        "anthropic",
        "h",
        "session",
        calls=1,
        tokens_in=80,
        tokens_out=12,
        cache_read=40,
    )
    totals, series = s.aggregate(since_bucket=0)
    assert len(totals) == 2
    pt = next(r for r in series if r["bucket"] == 100)
    # series keeps tokens split by channel (§6-F7)
    assert pt["embed_tokens_in"] == 200
    assert pt["llm_tokens_in"] == 80 and pt["llm_tokens_out"] == 12
    # cache split per channel — this row's cache_read was on the provider
    assert pt["llm_cache_read"] == 40
    assert pt["embed_cache_read"] == 0 and pt["llm_cache_write"] == 0


def test_series_downsamples_to_bucket_size(tmp_path):
    s = _store(tmp_path)
    # Three adjacent minute buckets; group them into 5-minute slots.
    s.record(100, "embedding", "openai", "m", "doc", chunks=1, tokens_in=10)
    s.record(101, "embedding", "openai", "m", "doc", chunks=1, tokens_in=20)
    s.record(107, "embedding", "openai", "m", "doc", chunks=1, tokens_in=30)
    # bucket_size=1 -> three distinct minute rows.
    _, fine = s.aggregate(since_bucket=0, bucket_size=1)
    assert {r["bucket"] for r in fine} == {100, 101, 107}
    # bucket_size=5 -> 100 and 101 collapse to slot 100; 107 -> slot 105.
    _, coarse = s.aggregate(since_bucket=0, bucket_size=5)
    by_bucket = {r["bucket"]: r["embed_tokens_in"] for r in coarse}
    assert by_bucket == {100: 30, 105: 30}


def test_token_series_by_source_splits_per_source(tmp_path):
    s = _store(tmp_path)
    s.record(100, "embedding", "openai", "m", "doc", tokens_in=200)
    s.record(100, "embedding", "openai", "m", "git", tokens_in=50)
    s.record(101, "embedding", "openai", "m", "doc", tokens_in=30)
    rows = s.token_series_by_source(since_bucket=0, bucket_size=1)
    by = {(r["bucket"], r["source"]): r["tokens_in"] for r in rows}
    assert by[(100, "doc")] == 200
    assert by[(100, "git")] == 50
    assert by[(101, "doc")] == 30


def test_prune_forever_when_retain_days_le_zero(tmp_path):
    s = _store(tmp_path)
    s.record(1, "embedding", "openai", "m", "doc", chunks=1)  # ancient bucket
    s.prune(now_bucket=1_000_000, retain_days=0)  # 0 == forever
    totals, _ = s.aggregate(since_bucket=0)
    assert totals, "retain_days<=0 must keep everything (§6-F1)"


def _day(day: int, minute: int = 0) -> int:
    """Minute bucket on a given day index (1440 minutes per day)."""
    return day * 1440 + minute


def test_prune_keeps_newest_n_active_days(tmp_path):
    s = _store(tmp_path)
    # Activity on days 0,1,2,5,9 (idle days 3,4,6,7,8 are gaps).
    for d in (0, 1, 2, 5, 9):
        s.record(_day(d, 30), "embedding", "openai", "m", "doc", chunks=1)
    # Retain 3 working days -> keep days 9,5,2; drop 0 and 1.
    s.prune(now_bucket=_day(9, 100), retain_days=3)
    days = {r["bucket"] // 1440 for r in s.aggregate(since_bucket=0)[1]}
    assert days == {2, 5, 9}, "idle days must not consume the retention budget"


def test_prune_noop_when_fewer_active_days_than_budget(tmp_path):
    s = _store(tmp_path)
    s.record(_day(0, 10), "embedding", "openai", "m", "doc", chunks=1)
    s.record(_day(40, 10), "embedding", "openai", "m", "doc", chunks=1)
    # Only 2 active days but budget 7 -> keep everything (a long-idle gap).
    s.prune(now_bucket=_day(40, 20), retain_days=7)
    days = {r["bucket"] // 1440 for r in s.aggregate(since_bucket=0)[1]}
    assert days == {0, 40}


def test_queue_sample_is_overwritten_not_summed(tmp_path):
    s = _store(tmp_path)
    s.sample_queue(100, "session", depth=500, sampled_at=10)
    s.sample_queue(100, "session", depth=698, sampled_at=20)
    latest = {r["source"]: r for r in s.queue_latest()}
    assert latest["session"]["depth"] == 698 and latest["session"]["sampled_at"] == 20


def test_v1_db_is_wiped_on_upgrade(tmp_path):
    """A pre-existing v1 (hourly) DB is dropped & recreated, not left mixed."""
    import sqlite3

    db = tmp_path / "usage.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE usage_metrics (hour_bucket INT, channel TEXT);"
        "PRAGMA user_version=1;"
    )
    conn.execute(
        "INSERT INTO usage_metrics (hour_bucket, channel) VALUES (495143, 'embedding')"
    )
    conn.commit()
    conn.close()

    s = UsageMetricsStore(db)  # opens v1 -> wipes -> v2 schema
    totals, series = s.aggregate(since_bucket=0)
    assert totals == [] and series == []
    # new minute-bucket schema works
    s.record(29_708_580, "embedding", "openai", "m", "doc", chunks=1)
    assert s.aggregate(since_bucket=0)[1][0]["bucket"] == 29_708_580
