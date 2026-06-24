"""Records router tests (Task 15).

Minimal FastAPI app with the router and a real RecordStore (in-memory SQLite).
Exercises the stats and revalidate endpoints without the full app lifespan.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.records import router
from brainpalace_server.storage.record_store import RecordStore


def _make_store_with_records(tmp_path) -> RecordStore:
    """Create a RecordStore with a few pre-populated records for testing."""
    db_path = tmp_path / "records.db"
    rs = RecordStore(db_path)
    # Insert a couple of records directly via SQLite
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO records (id, subject, metric, value, unit, ts, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("r1", "alice", "bodyweight", 70.0, "kg", "2026-01-01", 0.9),
    )
    conn.execute(
        "INSERT INTO records (id, subject, metric, value, unit, ts, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("r2", "bob", "bodyweight", 80.0, "kg", "2026-01-02", 0.4),
    )
    conn.commit()
    conn.close()
    return rs


@pytest.fixture
def client_with_records(tmp_path):
    """TestClient with a minimal app wiring the records router + a RecordStore."""
    rs = _make_store_with_records(tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/records")
    app.state.record_store = rs
    return TestClient(app)


@pytest.fixture
def client_no_records(tmp_path):
    """TestClient where record_store is None (disabled)."""
    app = FastAPI()
    app.include_router(router, prefix="/records")
    app.state.record_store = None
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /records/stats
# ---------------------------------------------------------------------------


def test_records_stats_endpoint(client_with_records):
    r = client_with_records.get("/records/stats")
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert "unverified" in body
    assert "metrics" in body
    assert body["total"] == 2
    assert body["unverified"] == 1  # bob's confidence < 0.7
    assert "bodyweight" in body["metrics"]


def test_records_stats_503_when_disabled(client_no_records):
    r = client_no_records.get("/records/stats")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# POST /records/revalidate
# ---------------------------------------------------------------------------


def test_records_revalidate_endpoint(client_with_records):
    r = client_with_records.post("/records/revalidate", json={"metric": "bodyweight"})
    assert r.status_code == 200
    assert "rescored" in r.json()
    # Only bob has confidence < 0.7 and metric=bodyweight → rescored=1
    assert r.json()["rescored"] == 1


def test_records_revalidate_no_metric(client_with_records):
    """Omitting metric rescores all unverified records."""
    r = client_with_records.post("/records/revalidate", json={})
    assert r.status_code == 200
    assert r.json()["rescored"] == 1


def test_records_revalidate_503_when_disabled(client_no_records):
    r = client_no_records.post("/records/revalidate", json={})
    assert r.status_code == 503
