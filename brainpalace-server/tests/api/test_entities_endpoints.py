"""/entities/* router (G5 Task 7) — person/alias/link over a REAL IdentityStore
on a temp db. Mirrors tests/api/test_ingest_endpoints.py's minimal-app fixture.
The engine ranks candidates; it never picks — resolve returns the ranked set."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.entities import router as entities_router
from brainpalace_server.storage.identity_store import IdentityStore


def _client(store) -> TestClient:
    app = FastAPI()
    app.include_router(entities_router, prefix="/entities")
    app.state.identity_store = store
    return TestClient(app)


def test_missing_store_is_503(tmp_path):
    client = _client(None)
    r = client.get("/entities/unresolved")
    assert r.status_code == 503


def test_person_alias_resolve_flow(tmp_path):
    store = IdentityStore(tmp_path / "identity.db")
    client = _client(store)

    r = client.post(
        "/entities/person", json={"kind": "person", "domain": "home", "name": "Ana"}
    )
    assert r.status_code == 200, r.text
    pid = r.json()["person_id"]

    r = client.post(
        "/entities/alias", json={"surface": "Mama", "person_id": pid, "scope": "spk"}
    )
    assert r.status_code == 200 and r.json() == {"ok": True}

    r = client.get(
        "/entities/resolve",
        params={"surface": "Mama", "scope": "spk", "at": "2026-07-09T00:00:00Z"},
    )
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    assert [c["person_id"] for c in cands] == [pid]


def test_link_unresolved_and_retract(tmp_path):
    store = IdentityStore(tmp_path / "identity.db")
    client = _client(store)

    # An unresolved link (no person_id) lands in the bucket.
    r = client.post(
        "/entities/link",
        json={
            "ref": "msg_1#0",
            "ref_kind": "span",
            "role": "mentioned",
            "method": "alias_match",
            "at": "2026-07-09T00:00:00Z",
            "surface": "Mama",
        },
    )
    assert r.status_code == 200, r.text
    lid = r.json()["link_id"]

    r = client.get("/entities/unresolved")
    assert r.status_code == 200
    assert [link["id"] for link in r.json()["links"]] == [lid]

    # backfill re-scores without resolving (still unresolved bucket).
    r = client.post("/entities/backfill")
    assert r.status_code == 200 and r.json()["rescored"] == 1

    r = client.delete(f"/entities/link/{lid}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get("/entities/unresolved").json()["links"] == []

    # retracting a missing link is a 404.
    assert client.delete("/entities/link/nope").status_code == 404
