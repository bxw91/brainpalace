"""Tests for GET /metrics/usage endpoint (Task 4).

Minimal FastAPI app with the metrics router wired and a real UsageMetricsStore
seeded via app.state — mirrors the pattern in test_records_endpoints.py.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.metrics import router
from brainpalace_server.storage.usage_metrics_store import UsageMetricsStore


@pytest.fixture
def usage_app(tmp_path):
    """App with a UsageMetricsStore seeded with one row in the current hour."""
    import time

    store = UsageMetricsStore(tmp_path / "usage.db")
    store.record(
        int(time.time()) // 60,
        "embedding",
        "openai",
        "text-embedding-3-large",
        "doc",
        chunks=5,
        calls=1,
        tokens_in=200,
    )
    app = FastAPI()
    app.include_router(router, prefix="/metrics")
    app.state.usage_metrics_store = store
    return app


@pytest.fixture
def disabled_usage_app():
    """App where usage_metrics_store is None (disabled)."""
    app = FastAPI()
    app.include_router(router, prefix="/metrics")
    app.state.usage_metrics_store = None
    return app


def test_usage_endpoint_returns_totals_series_queue(usage_app):
    client = TestClient(usage_app)
    r = client.get("/metrics/usage?window=24h")
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "24h" and "now_bucket" in body
    assert isinstance(body["totals"], list) and isinstance(body["series"], list)
    assert isinstance(body["queue"], list)


def test_queue_active_flag_reflects_extraction_mode(tmp_path):
    """Each backlog row is flagged active=False when the feature that drains it
    is off (doc/git → extraction mode, session → session mode)."""
    import time

    store = UsageMetricsStore(tmp_path / "usage.db")
    bucket = int(time.time()) // 60
    for src in ("doc", "git", "session"):
        store.sample_queue(bucket, src, 5, int(time.time()))
    app = FastAPI()
    app.include_router(router, prefix="/metrics")
    app.state.usage_metrics_store = store
    app.state.extraction_mode_doc = "off"
    app.state.extraction_mode_session = "subagent"
    rows = {
        q["source"]: q for q in TestClient(app).get("/metrics/usage").json()["queue"]
    }
    assert rows["doc"]["active"] is False  # extraction off
    assert rows["git"]["active"] is False  # extraction off
    assert rows["session"]["active"] is True  # session mode on


def test_queue_active_defaults_true_without_mode_state(usage_app):
    """Absent app.state extraction modes (bare app) default doc to off → inactive."""
    # usage_app has no extraction_mode_* set → getattr default "off".
    store = usage_app.state.usage_metrics_store
    import time

    store.sample_queue(int(time.time()) // 60, "doc", 3, int(time.time()))
    rows = {
        q["source"]: q
        for q in TestClient(usage_app).get("/metrics/usage").json()["queue"]
    }
    assert rows["doc"]["active"] is False


def test_usage_endpoint_503_when_disabled(disabled_usage_app):
    client = TestClient(disabled_usage_app)
    assert client.get("/metrics/usage?window=24h").status_code == 503


def test_window_maps_to_hours(usage_app):
    client = TestClient(usage_app)
    assert client.get("/metrics/usage?window=bogus").status_code == 422


def test_all_valid_windows_accepted(usage_app):
    """All four supported window strings should return 200."""
    client = TestClient(usage_app)
    for window in ("1h", "24h", "7d", "30d"):
        r = client.get(f"/metrics/usage?window={window}")
        assert r.status_code == 200, f"window={window} returned {r.status_code}"


def test_totals_contain_seeded_row(usage_app):
    """Seeded embedding row should appear in the totals."""
    client = TestClient(usage_app)
    r = client.get("/metrics/usage?window=30d")
    body = r.json()
    channels = [t["channel"] for t in body["totals"]]
    assert "embedding" in channels


def test_window_anchored_to_latest_data_not_wall_clock(tmp_path):
    """A 1h window with only old data still returns that data (anchored to the
    newest recorded bucket, not wall-clock now)."""
    import time

    store = UsageMetricsStore(tmp_path / "usage.db")
    old_bucket = int(time.time()) // 60 - 180  # 3 hours ago
    store.record(
        old_bucket, "embedding", "openai", "m", "doc", chunks=1, calls=1, tokens_in=10
    )
    app = FastAPI()
    app.include_router(router, prefix="/metrics")
    app.state.usage_metrics_store = store
    body = TestClient(app).get("/metrics/usage?window=1h").json()
    # Wall-clock-anchored 1h would be empty; data-anchored shows the old row.
    assert body["totals"], "expected totals anchored to newest data"
    assert any(s["embed_tokens_in"] == 10 for s in body["series"])


def test_response_shape_fields(usage_app):
    """Response must include all five top-level keys."""
    client = TestClient(usage_app)
    body = client.get("/metrics/usage?window=1h").json()
    for key in ("window", "now_bucket", "bucket_size", "totals", "series", "queue"):
        assert key in body, f"missing key: {key}"
