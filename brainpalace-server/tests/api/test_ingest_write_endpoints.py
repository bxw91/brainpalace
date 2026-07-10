"""POST /ingest/records + POST /ingest/references (Round 4 Stage 2, D1/D3).

Real RecordStore + ReferenceCatalogStore (SQLite) on app.state so the write
routes exercise the actual sink choke point (`aingest`) — salience,
ingested_at stamping, replace-by-source_id and write-time reference embedding
are inherited, never re-implemented in the router."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.ingest import router as ingest_router
from brainpalace_server.storage.record_store import RecordStore
from brainpalace_server.storage.reference_catalog_store import ReferenceCatalogStore


class _StubEmbedder:
    """Object shaped like the server's embedding generator: an async
    ``embed_chunks`` reading ``.text`` off each piece (what aingest calls to
    embed reference summaries)."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_chunks(self, chunks):  # noqa: ANN001
        self.calls.append([c.text for c in chunks])
        return [[0.1, 0.2, 0.3] for _ in chunks]


class _StubIngestService:
    """Stands in for DocumentIngestService — the reference route only reads its
    ``embedding_generator`` attribute to decide whether to embed at write time."""

    def __init__(self, embedder) -> None:  # noqa: ANN001
        self.embedding_generator = embedder


def _client(tmp_path, *, embedder=None):  # noqa: ANN001
    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.record_store = RecordStore(tmp_path / "records.db")
    app.state.reference_catalog_store = ReferenceCatalogStore(tmp_path / "refs.db")
    app.state.document_ingest_service = (
        _StubIngestService(embedder) if embedder is not None else None
    )
    client = TestClient(app)
    return client, app.state.record_store, app.state.reference_catalog_store


def _rec_item(**kw):
    base = {
        "subject": "electricity",
        "metric": "kwh",
        "value": 420.0,
        "domain": "home",
        "source": "meter",
        "source_id": "bill-1",
    }
    base.update(kw)
    return base


def _ref_item(**kw):
    base = {
        "pointer": "file:///scan/bill-1.pdf",
        "summary": "electricity bill",
        "domain": "home",
        "source": "scanner",
        "source_id": "bill-1",
    }
    base.update(kw)
    return base


def test_post_ingest_records_happy_path(tmp_path):
    client, rs, _ = _client(tmp_path)
    r = client.post(
        "/ingest/records",
        json={"items": [_rec_item()], "sensitivity": "private"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"records": 1}
    assert rs.record_count() == 1
    row = rs._conn.execute(
        "SELECT value, confidence, sensitivity, ingested_at FROM records"
    ).fetchone()
    assert row[0] == 420.0
    assert row[1] == 1.0  # caller-asserted default confidence
    assert row[2] == "private"
    assert row[3]  # ingested_at stamped by the sink
    # domain auto-registered by the router:
    from brainpalace_server.models.domains import is_known_domain

    assert is_known_domain("home")


def test_post_ingest_records_replace_by_source_id(tmp_path):
    client, rs, _ = _client(tmp_path)
    # First write: two distinct metrics under one source_id.
    client.post(
        "/ingest/records",
        json={
            "items": [
                _rec_item(metric="kwh", value=420.0),
                _rec_item(metric="cost", value=63.0),
            ]
        },
    )
    assert rs.record_count() == 2
    # Re-ingest the SAME source_id with a single record → replaces the batch.
    r = client.post("/ingest/records", json={"items": [_rec_item(value=430.0)]})
    assert r.status_code == 200 and r.json() == {"records": 1}
    assert rs.record_count() == 1
    sid = rs._conn.execute("SELECT DISTINCT source_id FROM records").fetchone()[0]
    assert sid == "bill-1"
    val = rs._conn.execute("SELECT value FROM records").fetchone()[0]
    assert val == 430.0


def test_post_ingest_records_provenance_violation_is_422(tmp_path):
    client, rs, _ = _client(tmp_path)
    r = client.post("/ingest/records", json={"items": [_rec_item(domain="")]})
    assert r.status_code == 422
    assert rs.record_count() == 0


def test_post_ingest_records_missing_store_is_503(tmp_path):
    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.record_store = None
    client = TestClient(app)
    r = client.post("/ingest/records", json={"items": [_rec_item()]})
    assert r.status_code == 503


def test_post_ingest_references_keyless_lands_unembedded_then_backfills(tmp_path):
    # No document_ingest_service → no embedder (D3 keyless path).
    client, _, refs = _client(tmp_path, embedder=None)
    r = client.post("/ingest/references", json={"items": [_ref_item()]})
    assert r.status_code == 200, r.text
    assert r.json() == {"references": 1}
    assert refs.count() == 1
    assert refs.count_unembedded() == 1  # landed, but unembedded
    # The documented backfill path re-attaches an embedding by id.
    ref = refs.unembedded_entries()[0]
    refs.set_embeddings([(ref.id, [0.1, 0.2, 0.3])])
    assert refs.count_unembedded() == 0


def test_post_ingest_references_embeds_at_write_when_provider_up(tmp_path):
    embedder = _StubEmbedder()
    client, _, refs = _client(tmp_path, embedder=embedder)
    r = client.post("/ingest/references", json={"items": [_ref_item()]})
    assert r.status_code == 200, r.text
    assert refs.count() == 1
    assert refs.count_unembedded() == 0  # embedded at write time
    assert embedder.calls == [["electricity bill"]]


def test_post_ingest_references_replace_by_source_id(tmp_path):
    client, _, refs = _client(tmp_path)
    client.post(
        "/ingest/references",
        json={
            "items": [
                _ref_item(pointer="p://a"),
                _ref_item(pointer="p://b"),
            ]
        },
    )
    assert refs.count() == 2
    r = client.post("/ingest/references", json={"items": [_ref_item(pointer="p://c")]})
    assert r.status_code == 200 and r.json() == {"references": 1}
    assert refs.count() == 1


def test_delete_source_full_forget_cascades_all_tiers(tmp_path):
    """DELETE /ingest/source/{source_id} (D2) drops chunks + records +
    references for one source_id, in one call, with per-tier counts —
    persons/aliases are out of scope here (identity survival is pinned at
    the DocumentIngestService.forget_source unit-test layer)."""
    from brainpalace_server.services.document_ingest_service import (
        DocumentIngestService,
        IngestDoc,
    )

    class _StubDocStorage:
        def __init__(self):
            self.rows: dict[str, dict] = {}

        async def get_existing_ids(self, ids):
            return set()

        async def get_ids_by_where(self, where):
            return set(self.rows)

        async def get_by_id(self, chunk_id):
            return self.rows.get(chunk_id)

        async def delete_by_ids(self, ids):
            n = 0
            for i in list(ids):
                if self.rows.pop(i, None) is not None:
                    n += 1
            return n

        async def upsert_documents(self, ids, embeddings, documents, metadatas):
            for i, e, d, m in zip(ids, embeddings, documents, metadatas):
                self.rows[i] = {"embedding": e, "document": d, "metadata": m}

    class _RealDocIngestEmbedder:
        async def embed_chunks(self, chunks):
            return [[0.1, 0.2, 0.3] for _ in chunks]

    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.record_store = RecordStore(tmp_path / "records.db")
    app.state.reference_catalog_store = ReferenceCatalogStore(tmp_path / "refs.db")
    doc_storage = _StubDocStorage()
    app.state.document_ingest_service = DocumentIngestService(
        embedding_generator=_RealDocIngestEmbedder(), storage_backend=doc_storage
    )
    client = TestClient(app)

    # Seed one source_id across all three tiers.
    import asyncio

    asyncio.run(
        app.state.document_ingest_service.ingest_documents(
            [
                IngestDoc(
                    text="ugovor o najmu",
                    domain="home",
                    source="scanner",
                    source_id="bill-1",
                )
            ]
        )
    )
    client.post("/ingest/records", json={"items": [_rec_item()]})
    client.post("/ingest/references", json={"items": [_ref_item()]})
    assert doc_storage.rows
    assert app.state.record_store.record_count() == 1
    assert app.state.reference_catalog_store.count() == 1

    r = client.delete("/ingest/source/bill-1")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "chunks_deleted": 1,
        "records_deleted": 1,
        "references_deleted": 1,
    }
    assert not doc_storage.rows
    assert app.state.record_store.record_count() == 0
    assert app.state.reference_catalog_store.count() == 0


def test_delete_source_full_forget_missing_all_stores_is_503(tmp_path):
    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.record_store = None
    app.state.reference_catalog_store = None
    app.state.document_ingest_service = None
    client = TestClient(app)
    r = client.delete("/ingest/source/bill-1")
    assert r.status_code == 503


def test_delete_source_full_forget_partial_stores_still_deletes_wired_ones(tmp_path):
    """Keyless server (no document_ingest_service): records/references still
    get forgotten — the endpoint doesn't 503 just because one tier is absent."""
    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.record_store = RecordStore(tmp_path / "records.db")
    app.state.reference_catalog_store = None
    app.state.document_ingest_service = None
    client = TestClient(app)
    client.post("/ingest/records", json={"items": [_rec_item()]})
    assert app.state.record_store.record_count() == 1

    r = client.delete("/ingest/source/bill-1")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "chunks_deleted": 0,
        "records_deleted": 1,
        "references_deleted": 0,
    }
    assert app.state.record_store.record_count() == 0


class _StubQueryCache:
    """Stands in for QueryCacheService — only ``invalidate_all`` matters."""

    def __init__(self) -> None:
        self.invalidate_calls = 0

    async def invalidate_all(self) -> None:
        self.invalidate_calls += 1


def test_delete_text_and_forget_both_invalidate_query_cache(tmp_path):
    """A source_id gone from storage must also stop being served from a
    cached hit taken before the delete — both the narrow text-delete and the
    full-forget cascade bump the query-cache generation."""
    from brainpalace_server.services.document_ingest_service import (
        DocumentIngestService,
        IngestDoc,
    )

    class _StubDocStorage:
        def __init__(self):
            self.rows: dict[str, dict] = {}

        async def get_existing_ids(self, ids):
            return set()

        async def get_ids_by_where(self, where):
            return set(self.rows)

        async def get_by_id(self, chunk_id):
            return self.rows.get(chunk_id)

        async def delete_by_ids(self, ids):
            n = 0
            for i in list(ids):
                if self.rows.pop(i, None) is not None:
                    n += 1
            return n

        async def upsert_documents(self, ids, embeddings, documents, metadatas):
            for i, e, d, m in zip(ids, embeddings, documents, metadatas):
                self.rows[i] = {"embedding": e, "document": d, "metadata": m}

    class _Embedder:
        async def embed_chunks(self, chunks):
            return [[0.1, 0.2, 0.3] for _ in chunks]

    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.document_ingest_service = DocumentIngestService(
        embedding_generator=_Embedder(), storage_backend=_StubDocStorage()
    )
    app.state.record_store = None
    app.state.reference_catalog_store = None
    app.state.query_cache = _StubQueryCache()
    client = TestClient(app)

    import asyncio

    asyncio.run(
        app.state.document_ingest_service.ingest_documents(
            [IngestDoc(text="a", domain="home", source="scanner", source_id="bill-1")]
        )
    )
    r = client.delete("/ingest/text/bill-1")
    assert r.status_code == 200, r.text
    assert app.state.query_cache.invalidate_calls == 1

    asyncio.run(
        app.state.document_ingest_service.ingest_documents(
            [IngestDoc(text="b", domain="home", source="scanner", source_id="bill-2")]
        )
    )
    r = client.delete("/ingest/source/bill-2")
    assert r.status_code == 200, r.text
    assert app.state.query_cache.invalidate_calls == 2


def test_delete_text_endpoint_stays_chunks_only(tmp_path):
    """DELETE /ingest/text/{source_id} keeps its narrow, published meaning —
    unaffected by the new cascade endpoint."""
    from brainpalace_server.services.document_ingest_service import (
        DocumentIngestService,
        IngestDoc,
    )

    class _StubDocStorage:
        def __init__(self):
            self.rows: dict[str, dict] = {}

        async def get_existing_ids(self, ids):
            return set()

        async def get_ids_by_where(self, where):
            return set(self.rows)

        async def get_by_id(self, chunk_id):
            return self.rows.get(chunk_id)

        async def delete_by_ids(self, ids):
            n = 0
            for i in list(ids):
                if self.rows.pop(i, None) is not None:
                    n += 1
            return n

        async def upsert_documents(self, ids, embeddings, documents, metadatas):
            for i, e, d, m in zip(ids, embeddings, documents, metadatas):
                self.rows[i] = {"embedding": e, "document": d, "metadata": m}

    class _Embedder:
        async def embed_chunks(self, chunks):
            return [[0.1, 0.2, 0.3] for _ in chunks]

    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.record_store = RecordStore(tmp_path / "records.db")
    app.state.reference_catalog_store = ReferenceCatalogStore(tmp_path / "refs.db")
    doc_storage = _StubDocStorage()
    app.state.document_ingest_service = DocumentIngestService(
        embedding_generator=_Embedder(), storage_backend=doc_storage
    )
    client = TestClient(app)

    import asyncio

    asyncio.run(
        app.state.document_ingest_service.ingest_documents(
            [
                IngestDoc(
                    text="ugovor o najmu",
                    domain="home",
                    source="scanner",
                    source_id="bill-1",
                )
            ]
        )
    )
    client.post("/ingest/records", json={"items": [_rec_item()]})
    client.post("/ingest/references", json={"items": [_ref_item()]})

    r = client.delete("/ingest/text/bill-1")
    assert r.status_code == 200, r.text
    assert r.json() == {"chunks_deleted": 1}
    assert not doc_storage.rows
    # records + references untouched — the text-only endpoint doesn't cascade.
    assert app.state.record_store.record_count() == 1
    assert app.state.reference_catalog_store.count() == 1


@pytest.mark.asyncio
async def test_router_vs_sink_parity(tmp_path):
    """Same records through the HTTP route and directly through `aingest` land
    identically (the route adds no behavior beyond building the emitted items)."""
    from brainpalace_server.api.routers.ingest import RecordIngestItem, _record_id
    from brainpalace_server.ingestion.adapter import EmittedRecord
    from brainpalace_server.ingestion.sink import aingest, items_adapter
    from brainpalace_server.models.domains import register_domain
    from brainpalace_server.models.record import RecordCandidate

    # HTTP path.
    client, rs_http, _ = _client(tmp_path)
    client.post("/ingest/records", json={"items": [_rec_item()]})

    # Direct sink path into a separate store, same derived id + fields.
    register_domain("home")
    rs_direct = RecordStore(tmp_path / "records_direct.db")
    item = RecordIngestItem(**_rec_item())
    emitted = EmittedRecord(
        candidate=RecordCandidate(
            subject=item.subject,
            metric=item.metric,
            value=item.value,
            unit=item.unit,
            ts=item.ts,
        ),
        id=_record_id(item),
        domain=item.domain,
        source=item.source,
        source_id=item.source_id,
        confidence=item.confidence,
        properties=item.properties,
    )
    await aingest(
        items_adapter([emitted]),
        None,
        record_store=rs_direct,
        ingested_at="2026-07-10T00:00:00Z",
        sensitivity="normal",
    )

    cols = "id, subject, metric, value, confidence, salience, sensitivity, source_id"
    http_row = rs_http._conn.execute(f"SELECT {cols} FROM records").fetchone()
    direct_row = rs_direct._conn.execute(f"SELECT {cols} FROM records").fetchone()
    assert http_row == direct_row


# ------------------------------------------------ POST-write cache invalidation (A5)
def test_post_ingest_text_invalidates_query_cache(tmp_path):
    """A write via POST /ingest/text must also stop a cached query hit taken
    before it from being served stale — mirrors the DELETE-side invalidation
    above (D3: symmetry, same helper, same placement)."""
    from brainpalace_server.services.document_ingest_service import (
        DocumentIngestService,
    )

    class _StubDocStorage:
        def __init__(self):
            self.rows: dict[str, dict] = {}

        async def get_existing_ids(self, ids):
            return set()

        async def get_ids_by_where(self, where):
            return set(self.rows)

        async def get_by_id(self, chunk_id):
            return self.rows.get(chunk_id)

        async def delete_by_ids(self, ids):
            return 0

        async def upsert_documents(self, ids, embeddings, documents, metadatas):
            for i, e, d, m in zip(ids, embeddings, documents, metadatas):
                self.rows[i] = {"embedding": e, "document": d, "metadata": m}

    class _Embedder:
        async def embed_chunks(self, chunks):
            return [[0.1, 0.2, 0.3] for _ in chunks]

    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.document_ingest_service = DocumentIngestService(
        embedding_generator=_Embedder(), storage_backend=_StubDocStorage()
    )
    app.state.query_cache = _StubQueryCache()
    client = TestClient(app)

    r = client.post(
        "/ingest/text",
        json={
            "items": [
                {
                    "text": "a",
                    "domain": "home",
                    "source": "scanner",
                    "source_id": "bill-1",
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert app.state.query_cache.invalidate_calls == 1


def test_post_ingest_text_failure_does_not_invalidate_query_cache(tmp_path):
    """A 422 (reserved-metadata collision) must NOT invalidate the cache."""
    from brainpalace_server.services.document_ingest_service import (
        DocumentIngestService,
    )

    class _StubDocStorage:
        async def get_existing_ids(self, ids):
            return set()

        async def get_ids_by_where(self, where):
            return set()

        async def get_by_id(self, chunk_id):
            return None

        async def delete_by_ids(self, ids):
            return 0

        async def upsert_documents(self, ids, embeddings, documents, metadatas):
            pass

    class _Embedder:
        async def embed_chunks(self, chunks):
            return [[0.1, 0.2, 0.3] for _ in chunks]

    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.document_ingest_service = DocumentIngestService(
        embedding_generator=_Embedder(), storage_backend=_StubDocStorage()
    )
    app.state.query_cache = _StubQueryCache()
    client = TestClient(app)

    r = client.post(
        "/ingest/text",
        json={
            "items": [
                {
                    "text": "a",
                    "domain": "home",
                    "source": "scanner",
                    "source_id": "bill-1",
                    "metadata": {"domain": "clash"},
                }
            ]
        },
    )
    assert r.status_code == 422, r.text
    assert app.state.query_cache.invalidate_calls == 0


def test_post_ingest_text_missing_provider_does_not_invalidate_query_cache(tmp_path):
    """A 503 (no embedding provider configured) must NOT invalidate the cache."""
    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.document_ingest_service = None
    app.state.query_cache = _StubQueryCache()
    client = TestClient(app)

    r = client.post(
        "/ingest/text",
        json={
            "items": [
                {
                    "text": "a",
                    "domain": "home",
                    "source": "scanner",
                    "source_id": "bill-1",
                }
            ]
        },
    )
    assert r.status_code == 503, r.text
    assert app.state.query_cache.invalidate_calls == 0


def test_post_ingest_records_invalidates_query_cache(tmp_path):
    client, rs, _ = _client(tmp_path)
    client.app.state.query_cache = _StubQueryCache()
    r = client.post("/ingest/records", json={"items": [_rec_item()]})
    assert r.status_code == 200, r.text
    assert client.app.state.query_cache.invalidate_calls == 1


def test_post_ingest_records_failure_does_not_invalidate_query_cache(tmp_path):
    client, rs, _ = _client(tmp_path)
    client.app.state.query_cache = _StubQueryCache()
    r = client.post("/ingest/records", json={"items": [_rec_item(domain="")]})
    assert r.status_code == 422, r.text
    assert client.app.state.query_cache.invalidate_calls == 0


def test_post_ingest_records_missing_store_does_not_invalidate_query_cache(tmp_path):
    app = FastAPI()
    app.include_router(ingest_router, prefix="/ingest")
    app.state.record_store = None
    app.state.query_cache = _StubQueryCache()
    client = TestClient(app)
    r = client.post("/ingest/records", json={"items": [_rec_item()]})
    assert r.status_code == 503, r.text
    assert app.state.query_cache.invalidate_calls == 0


def test_post_ingest_references_invalidates_query_cache(tmp_path):
    client, _, refs = _client(tmp_path)
    client.app.state.query_cache = _StubQueryCache()
    r = client.post("/ingest/references", json={"items": [_ref_item()]})
    assert r.status_code == 200, r.text
    assert client.app.state.query_cache.invalidate_calls == 1


def test_post_ingest_references_failure_does_not_invalidate_query_cache(tmp_path):
    client, _, refs = _client(tmp_path)
    client.app.state.query_cache = _StubQueryCache()
    r = client.post("/ingest/references", json={"items": [_ref_item(domain="")]})
    assert r.status_code == 422, r.text
    assert client.app.state.query_cache.invalidate_calls == 0
