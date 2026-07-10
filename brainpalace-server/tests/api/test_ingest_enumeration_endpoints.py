"""GET /ingest/sources + GET /ingest/text/{source_id} (Round 4 Stage 5, D5).

Mounts the ingest router with a real DocumentIngestService over a faithful
fake storage (get_by_id returns {text, metadata, embedding}, like the live
backend), seeds through the real ingest pipeline, then drives the two read
endpoints over HTTP.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.ingest import router as ingest_router
from brainpalace_server.services.document_ingest_service import (
    DocumentIngestService,
    IngestDoc,
)


class _Embedder:
    async def embed_chunks(self, chunks):  # noqa: ANN001
        return [[0.1, 0.2, 0.3] for _ in chunks]


class _FakeStorage:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def get_existing_ids(self, ids):  # noqa: ANN001
        return {i for i in ids if i in self.rows}

    async def get_ids_by_where(self, where):  # noqa: ANN001
        conds = where.get("$and", [where])

        def match(meta: dict) -> bool:
            return all(meta.get(k) == v for c in conds for k, v in c.items())

        return {i for i, r in self.rows.items() if match(r["metadata"])}

    async def get_by_id(self, chunk_id):  # noqa: ANN001
        return self.rows.get(chunk_id)

    async def delete_by_ids(self, ids):  # noqa: ANN001
        n = 0
        for i in list(ids):
            if self.rows.pop(i, None) is not None:
                n += 1
        return n

    async def upsert_documents(
        self, ids, embeddings, documents, metadatas
    ):  # noqa: ANN001,E501
        for i, e, d, m in zip(ids, embeddings, documents, metadatas):
            self.rows[i] = {"text": d, "metadata": m, "embedding": e}


def _client(*, service=True):  # noqa: ANN001
    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.document_ingest_service = (
        DocumentIngestService(
            embedding_generator=_Embedder(), storage_backend=_FakeStorage()
        )
        if service
        else None
    )
    return TestClient(app), app.state.document_ingest_service


def _seed(
    svc, *, domain, source, source_id, sensitivity="normal", text="hello"
):  # noqa: ANN001,E501
    asyncio.run(
        svc.ingest_documents(
            [IngestDoc(text=text, domain=domain, source=source, source_id=source_id)],
            sensitivity=sensitivity,
        )
    )


# ---------------------------------------------------------------------------
# GET /ingest/sources
# ---------------------------------------------------------------------------


def test_get_sources_lists_distinct_source_ids():
    client, svc = _client()
    _seed(svc, domain="home", source="scanner", source_id="bill-1")
    _seed(svc, domain="home", source="scanner", source_id="bill-2")

    r = client.get("/ingest/sources")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert [s["source_id"] for s in body["sources"]] == ["bill-1", "bill-2"]
    assert body["sources"][0]["source"] == "scanner"  # raw, not display URI


def test_get_sources_filter_by_domain_and_source():
    client, svc = _client()
    _seed(svc, domain="home", source="scanner", source_id="bill-1")
    _seed(svc, domain="work", source="email", source_id="msg-1")

    r = client.get("/ingest/sources", params={"domain": "work"})
    assert [s["source_id"] for s in r.json()["sources"]] == ["msg-1"]

    r = client.get("/ingest/sources", params={"source": "scanner"})
    assert [s["source_id"] for s in r.json()["sources"]] == ["bill-1"]


def test_get_sources_empty_index_is_empty_list_not_404():
    client, _ = _client()
    r = client.get("/ingest/sources")
    assert r.status_code == 200
    assert r.json() == {"sources": [], "total": 0}


def test_get_sources_sensitivity_default_deny():
    client, svc = _client()
    _seed(
        svc, domain="home", source="scanner", source_id="bill-1", sensitivity="private"
    )
    _seed(svc, domain="home", source="scanner", source_id="bill-2")

    r = client.get("/ingest/sources")
    assert [s["source_id"] for s in r.json()["sources"]] == ["bill-2"]

    r = client.get("/ingest/sources", params={"include_sensitive": True})
    assert [s["source_id"] for s in r.json()["sources"]] == ["bill-1", "bill-2"]


def test_get_sources_missing_service_is_503():
    client, _ = _client(service=False)
    r = client.get("/ingest/sources")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# GET /ingest/text/{source_id}
# ---------------------------------------------------------------------------


def test_get_source_chunks_returns_chunks():
    client, svc = _client()
    _seed(svc, domain="home", source="scanner", source_id="bill-1", text="ugovor")

    r = client.get("/ingest/text/bill-1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_id"] == "bill-1"
    assert body["total"] == 1
    assert body["chunks"][0]["text"] == "ugovor"
    assert body["chunks"][0]["metadata"]["domain"] == "home"


def test_get_source_chunks_pagination():
    client, svc = _client()

    class _Chunker:
        async def chunk_single_document(self, loaded):  # noqa: ANN001
            from types import SimpleNamespace

            return [SimpleNamespace(text=f"c{i}") for i in range(5)]

    svc.chunker = _Chunker()
    _seed(svc, domain="home", source="scanner", source_id="bill-1")

    r = client.get("/ingest/text/bill-1", params={"offset": 0, "limit": 2})
    assert r.json()["total"] == 5
    assert [c["text"] for c in r.json()["chunks"]] == ["c0", "c1"]

    r = client.get("/ingest/text/bill-1", params={"offset": 4, "limit": 2})
    assert [c["text"] for c in r.json()["chunks"]] == ["c4"]

    r = client.get("/ingest/text/bill-1", params={"offset": 10, "limit": 2})
    assert r.json()["chunks"] == []
    assert r.json()["total"] == 5


def test_get_source_chunks_unknown_source_id_is_empty_not_404():
    client, _ = _client()
    r = client.get("/ingest/text/nope")
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["chunks"] == []


def test_get_source_chunks_sensitivity_default_deny():
    client, svc = _client()
    _seed(
        svc, domain="home", source="scanner", source_id="bill-1", sensitivity="private"
    )

    r = client.get("/ingest/text/bill-1")
    assert r.status_code == 200
    assert r.json()["total"] == 0

    r = client.get("/ingest/text/bill-1", params={"include_sensitive": True})
    assert r.json()["total"] == 1


def test_get_source_chunks_missing_service_is_503():
    client, _ = _client(service=False)
    r = client.get("/ingest/text/bill-1")
    assert r.status_code == 503
