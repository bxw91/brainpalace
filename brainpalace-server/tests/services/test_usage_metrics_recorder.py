# tests/services/test_usage_metrics_recorder.py
import brainpalace_server.services.usage_metrics as um
from brainpalace_server.storage.usage_metrics_store import UsageMetricsStore


def test_record_usage_noop_when_disabled(tmp_path):
    um.set_usage_store(None)  # disabled / not wired
    um.record_usage("embedding", "openai", "m", "doc", chunks=1)  # must not raise


def test_record_usage_writes_when_enabled(tmp_path):
    store = UsageMetricsStore(tmp_path / "u.db")
    um.set_usage_store(store)
    try:
        um.record_usage("embedding", "openai", "m", "doc", chunks=3, tokens_in=9)
        totals, _ = store.aggregate(since_bucket=0)
        assert totals[0]["chunks"] == 3 and totals[0]["tokens_in"] == 9
    finally:
        um.set_usage_store(None)


def test_usage_scope_sets_and_resets(tmp_path):
    assert um.current_usage_source() == "unknown"
    with um.usage_scope("session"):
        assert um.current_usage_source() == "session"
    assert um.current_usage_source() == "unknown"  # reset via Token (§6-F4)


def test_record_usage_failure_bumps_dropped(monkeypatch, tmp_path):
    store = UsageMetricsStore(tmp_path / "u.db")
    um.set_usage_store(store)
    monkeypatch.setattr(
        store, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    before = um.dropped_writes()
    try:
        um.record_usage("embedding", "openai", "m", "doc", chunks=1)  # swallowed
        assert um.dropped_writes() == before + 1  # observable, not silent (§6-F5)
    finally:
        um.set_usage_store(None)
