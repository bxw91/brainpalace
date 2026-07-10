"""Round 4 D5 — DocumentIngestService.list_sources / get_source_chunks.

Seeds via the REAL ``ingest_documents`` pipeline (chunk → metadata stamp →
upsert) against a fake storage that mirrors the live backend's ``get_by_id``
shape ({text, metadata, embedding}), so enumeration is exercised end-to-end
rather than against hand-built rows.
"""

from __future__ import annotations

import pytest

from brainpalace_server.services.document_ingest_service import (
    DocumentIngestService,
    IngestDoc,
)


class _Embedder:
    async def embed_chunks(self, chunks):  # noqa: ANN001
        return [[0.1, 0.2, 0.3] for _ in chunks]


class _FakeStorage:
    """Mirrors the live backend contract: upsert stores text/metadata/
    embedding; get_by_id returns that shape; get_ids_by_where honours the
    ``$and`` dialect the delete/enumeration paths use."""

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


def _svc() -> tuple[DocumentIngestService, _FakeStorage]:
    store = _FakeStorage()
    svc = DocumentIngestService(embedding_generator=_Embedder(), storage_backend=store)
    return svc, store


async def _seed(svc: DocumentIngestService, **kw) -> None:
    kw.setdefault("text", "hello world")
    await svc.ingest_documents(
        [
            IngestDoc(
                text=kw["text"],
                domain=kw["domain"],
                source=kw["source"],
                source_id=kw["source_id"],
            )
        ],
        sensitivity=kw.get("sensitivity", "normal"),
    )


# ---------------------------------------------------------------------------
# list_sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_groups_distinct_source_ids() -> None:
    svc, _ = _svc()
    await _seed(svc, domain="home", source="scanner", source_id="bill-1")
    await _seed(svc, domain="home", source="scanner", source_id="bill-2")

    sources = await svc.list_sources()
    assert [s["source_id"] for s in sources] == ["bill-1", "bill-2"]  # sorted
    for s in sources:
        assert s["domain"] == "home"
        assert s["source"] == "scanner"  # raw label, not the display URI
        assert s["chunk_count"] == 1
        assert s["ingested_at"]


@pytest.mark.asyncio
async def test_list_sources_reports_raw_source_not_display_uri() -> None:
    svc, _ = _svc()
    await _seed(svc, domain="home", source="scanner", source_id="bill-1")
    sources = await svc.list_sources()
    assert sources[0]["source"] == "scanner"
    assert "ingest://" not in sources[0]["source"]


@pytest.mark.asyncio
async def test_list_sources_filter_by_domain() -> None:
    svc, _ = _svc()
    await _seed(svc, domain="home", source="scanner", source_id="bill-1")
    await _seed(svc, domain="work", source="email", source_id="msg-1")

    home = await svc.list_sources(domain="home")
    assert [s["source_id"] for s in home] == ["bill-1"]
    work = await svc.list_sources(domain="work")
    assert [s["source_id"] for s in work] == ["msg-1"]


@pytest.mark.asyncio
async def test_list_sources_filter_by_source() -> None:
    svc, _ = _svc()
    await _seed(svc, domain="home", source="scanner", source_id="bill-1")
    await _seed(svc, domain="home", source="email", source_id="msg-1")

    scanned = await svc.list_sources(source="scanner")
    assert [s["source_id"] for s in scanned] == ["bill-1"]


@pytest.mark.asyncio
async def test_list_sources_empty_index_returns_empty_list() -> None:
    svc, _ = _svc()
    assert await svc.list_sources() == []


@pytest.mark.asyncio
async def test_list_sources_sensitivity_default_deny() -> None:
    svc, _ = _svc()
    await _seed(
        svc, domain="home", source="scanner", source_id="bill-1", sensitivity="private"
    )
    await _seed(svc, domain="home", source="scanner", source_id="bill-2")

    default = await svc.list_sources()
    assert [s["source_id"] for s in default] == ["bill-2"]  # private hidden

    revealed = await svc.list_sources(include_sensitive=True)
    assert [s["source_id"] for s in revealed] == ["bill-1", "bill-2"]


@pytest.mark.asyncio
async def test_list_sources_chunk_count_multichunk() -> None:
    """A source with several chunks reports the true chunk_count."""
    svc, store = _svc()

    class _Chunker:
        async def chunk_single_document(self, loaded):  # noqa: ANN001
            from types import SimpleNamespace

            return [SimpleNamespace(text=t) for t in ("a", "b", "c")]

    svc.chunker = _Chunker()
    await _seed(svc, domain="home", source="scanner", source_id="bill-1")

    sources = await svc.list_sources()
    assert sources[0]["chunk_count"] == 3


# ---------------------------------------------------------------------------
# get_source_chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_source_chunks_returns_id_text_metadata() -> None:
    svc, _ = _svc()
    await _seed(svc, text="ugovor", domain="home", source="scanner", source_id="bill-1")
    result = await svc.get_source_chunks("bill-1")
    assert result["source_id"] == "bill-1"
    assert result["total"] == 1
    chunk = result["chunks"][0]
    assert chunk["chunk_id"]
    assert chunk["text"] == "ugovor"
    assert chunk["metadata"]["domain"] == "home"
    assert "_idx" not in chunk  # internal sort key stripped


@pytest.mark.asyncio
async def test_get_source_chunks_unknown_source_id_is_empty_not_404() -> None:
    svc, _ = _svc()
    result = await svc.get_source_chunks("nope")
    assert result == {
        "source_id": "nope",
        "total": 0,
        "offset": 0,
        "limit": 50,
        "chunks": [],
    }


@pytest.mark.asyncio
async def test_get_source_chunks_pagination_boundaries() -> None:
    svc, _ = _svc()

    class _Chunker:
        async def chunk_single_document(self, loaded):  # noqa: ANN001
            from types import SimpleNamespace

            return [SimpleNamespace(text=f"c{i}") for i in range(5)]

    svc.chunker = _Chunker()
    await _seed(svc, domain="home", source="scanner", source_id="bill-1")

    # offset 0
    first = await svc.get_source_chunks("bill-1", offset=0, limit=2)
    assert first["total"] == 5
    assert [c["text"] for c in first["chunks"]] == ["c0", "c1"]  # chunk_index order

    # mid
    mid = await svc.get_source_chunks("bill-1", offset=2, limit=2)
    assert [c["text"] for c in mid["chunks"]] == ["c2", "c3"]

    # past end
    past = await svc.get_source_chunks("bill-1", offset=10, limit=2)
    assert past["chunks"] == []
    assert past["total"] == 5  # total is the full visible count, not the page


@pytest.mark.asyncio
async def test_get_source_chunks_sensitivity_default_deny() -> None:
    svc, _ = _svc()
    await _seed(
        svc, domain="home", source="scanner", source_id="bill-1", sensitivity="private"
    )

    default = await svc.get_source_chunks("bill-1")
    assert default["total"] == 0
    assert default["chunks"] == []

    revealed = await svc.get_source_chunks("bill-1", include_sensitive=True)
    assert revealed["total"] == 1
