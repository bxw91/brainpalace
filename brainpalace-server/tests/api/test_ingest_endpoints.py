"""POST /ingest/text + DELETE /ingest/text/{source_id} (spec Item 3).

Minimal FastAPI app wiring the ingest router + a fake DocumentIngestService
on app.state — mirrors tests/api/test_records_endpoints.py's fixture style.
The fake honors the real service's reserved-metadata ValueError contract so
the router's 422 mapping is exercised for real."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.ingest import router as ingest_router
from brainpalace_server.services.document_ingest_service import (
    RESERVED_METADATA_KEYS,
)


class FakeIngestService:
    def __init__(self):
        self.docs = []
        self.deleted = []

    async def ingest_documents(
        self, docs, *, sensitivity="normal", language=None, ingested_at=None
    ):
        for d in docs:
            clash = RESERVED_METADATA_KEYS & set(d.metadata)
            if clash:
                raise ValueError(f"metadata uses reserved key(s): {sorted(clash)}")
        self.docs.extend(docs)
        return {
            "chunks_new": len(docs),
            "chunks_kept": 0,
            "chunks_deleted": 0,
            "chunk_ids": [f"ing_{i}" for i in range(len(docs))],
            "source_ids": sorted({d.source_id for d in docs}),
        }

    async def delete_source(self, source_id):
        self.deleted.append(source_id)
        return {"chunks_deleted": 2}


def _client_with_fake_service(fake) -> TestClient:
    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.document_ingest_service = fake
    return TestClient(app)


def test_post_ingest_text_happy_path():
    fake = FakeIngestService()
    client = _client_with_fake_service(fake)
    r = client.post(
        "/ingest/text",
        json={
            "items": [
                {
                    "text": "racun 420 kn",
                    "domain": "home",
                    "source": "scanner",
                    "source_id": "s1",
                    "metadata": {"page": "1"},
                }
            ],
            "sensitivity": "private",
            "language": "hr",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chunks_new"] == 1 and body["source_ids"] == ["s1"]
    # domain auto-registered:
    from brainpalace_server.models.domains import is_known_domain

    assert is_known_domain("home")


def test_post_ingest_reserved_metadata_is_422():
    client = _client_with_fake_service(FakeIngestService())
    r = client.post(
        "/ingest/text",
        json={
            "items": [
                {
                    "text": "x",
                    "domain": "home",
                    "source": "s",
                    "source_id": "s1",
                    "metadata": {"domain": "evil"},
                }
            ],
        },
    )
    assert r.status_code == 422


def test_post_ingest_missing_service_is_503():
    client = _client_with_fake_service(None)
    r = client.post("/ingest/text", json={"items": []})
    assert r.status_code == 503


def test_delete_ingest_source():
    fake = FakeIngestService()
    client = _client_with_fake_service(fake)
    r = client.delete("/ingest/text/s1")
    assert r.status_code == 200 and r.json() == {"chunks_deleted": 2}
    assert fake.deleted == ["s1"]
