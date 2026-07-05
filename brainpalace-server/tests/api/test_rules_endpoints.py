import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.records import router as records_router
from brainpalace_server.api.routers.rules import router as rules_router
from brainpalace_server.indexing import record_validation
from brainpalace_server.storage.record_store import RecordStore
from brainpalace_server.storage.taught_rule_store import TaughtRuleStore


@pytest.fixture
def client(tmp_path):
    record_validation.reset_validators()
    app = FastAPI()
    app.include_router(rules_router, prefix="/rules", tags=["Rules"])
    app.include_router(records_router, prefix="/records", tags=["Records"])
    app.state.taught_rule_store = TaughtRuleStore(tmp_path / "rules.db")
    app.state.record_store = RecordStore(tmp_path / "records.db")
    yield TestClient(app)
    record_validation.reset_validators()


def test_add_list_get_retire(client):
    r = client.post(
        "/rules",
        json={
            "owner": "user",
            "metric": "weight",
            "unit": "kg",
            "value_min": 60,
            "value_max": 120,
            "tier": "HIGH",
        },
    )
    assert r.status_code == 200
    rid = r.json()["id"]
    assert any(x["id"] == rid for x in client.get("/rules").json()["rules"])
    assert client.get(f"/rules/{rid}").json()["metric"] == "weight"
    assert client.post(f"/rules/{rid}/retire").json()["retired"] is True
    assert client.get("/rules").json()["rules"] == []


def test_add_bad_tier_returns_400(client):
    r = client.post("/rules", json={"owner": "user", "metric": "w", "tier": "X"})
    assert r.status_code == 400


def test_recompute_salience(client):
    from brainpalace_server.models.record import Record

    client.app.state.record_store.insert_records(
        [Record(id="a", subject="s", metric="m", value=1.0)]
    )
    r = client.post("/records/recompute-salience", json={})
    assert r.status_code == 200
    assert r.json()["rescored"] == 1
