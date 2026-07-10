"""DocumentIngestService — spec Item 3 core pipeline.

Fakes for embedding + storage so tests are hermetic and assert the
embed-frugal contract: unchanged text is never re-embedded, but its
metadata is refreshed."""

import pytest

from brainpalace_server.services.document_ingest_service import (
    RESERVED_METADATA_KEYS,
    DocumentIngestService,
    IngestDoc,
    forget_source,
    ingest_display_source,
)


class FakeEmbedder:
    def __init__(self):
        self.embedded_texts: list[str] = []

    async def embed_chunks(self, chunks):
        self.embedded_texts.extend(c.text for c in chunks)
        return [[0.1, 0.2, 0.3] for _ in chunks]


class FakeStorage:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    async def get_existing_ids(self, ids):
        return {i for i in ids if i in self.rows}

    async def get_ids_by_where(self, where):
        def match(meta):
            conds = where.get("$and", [where])
            return all(meta.get(k) == v for c in conds for k, v in c.items())

        return {i for i, r in self.rows.items() if match(r["metadata"])}

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


def _svc():
    emb, store = FakeEmbedder(), FakeStorage()
    return (
        DocumentIngestService(embedding_generator=emb, storage_backend=store),
        emb,
        store,
    )


def _doc(text="Ugovor o najmu stana, strana 2.", **kw):
    base = {"domain": "home", "source": "scanner", "source_id": "scan-0042"}
    base.update(kw)
    return IngestDoc(text=text, **base)


@pytest.mark.asyncio
async def test_ingest_stamps_reserved_metadata():
    svc, emb, store = _svc()
    out = await svc.ingest_documents([_doc()], sensitivity="private", language="hr")
    assert out["chunks_new"] >= 1
    meta = next(iter(store.rows.values()))["metadata"]
    assert meta["domain"] == "home"
    assert meta["source"] == ingest_display_source("home", "scanner", "scan-0042")
    assert meta["source_id"] == "scan-0042"
    assert meta["sensitivity"] == "private"
    assert meta["text_language"] == "hr"
    assert meta["source_type"] == "ingest"
    assert meta["ingested_at"]
    assert meta["authority"] == "authoritative"


def test_authority_is_a_reserved_metadata_key():
    assert "authority" in RESERVED_METADATA_KEYS


@pytest.mark.asyncio
async def test_reserved_authority_key_collision_raises():
    svc, _, _ = _svc()
    with pytest.raises(ValueError, match="reserved"):
        await svc.ingest_documents([_doc(metadata={"authority": "reference"})])


@pytest.mark.asyncio
async def test_reingest_unchanged_text_reembeds_nothing_but_refreshes_metadata():
    svc, emb, store = _svc()
    await svc.ingest_documents([_doc(metadata={"complete": "false"})])
    first_embeds = len(emb.embedded_texts)
    out = await svc.ingest_documents([_doc(metadata={"complete": "true"})])
    assert len(emb.embedded_texts) == first_embeds  # zero new embeds
    assert out["chunks_new"] == 0 and out["chunks_kept"] >= 1
    meta = next(iter(store.rows.values()))["metadata"]
    assert meta["complete"] == "true"  # metadata refreshed


@pytest.mark.asyncio
async def test_reingest_changed_text_replaces_stale_chunks():
    svc, emb, store = _svc()
    await svc.ingest_documents([_doc(text="stari tekst dokumenta")])
    old_ids = set(store.rows)
    out = await svc.ingest_documents([_doc(text="potpuno novi tekst dokumenta")])
    assert out["chunks_deleted"] == len(old_ids)  # stale gone
    assert not (old_ids & set(store.rows))  # replaced, not appended


@pytest.mark.asyncio
async def test_reserved_metadata_key_collision_raises():
    svc, _, _ = _svc()
    with pytest.raises(ValueError, match="reserved"):
        await svc.ingest_documents([_doc(metadata={"domain": "evil"})])


@pytest.mark.asyncio
async def test_delete_source_removes_all_chunks():
    svc, _, store = _svc()
    await svc.ingest_documents([_doc()])
    out = await svc.delete_source("scan-0042")
    assert out["chunks_deleted"] >= 1 and not store.rows


class FakeStoreWithDeleteBySource:
    """Stands in for RecordStore/ReferenceCatalogStore — only the
    ``delete_by_source`` shape `forget_source` calls."""

    def __init__(self):
        self.rows_by_source: dict[str, int] = {}

    def delete_by_source(self, source_id):
        return self.rows_by_source.pop(source_id, 0)


@pytest.mark.asyncio
async def test_forget_source_cascades_all_three_tiers():
    svc, _, store = _svc()
    await svc.ingest_documents([_doc()])
    rs = FakeStoreWithDeleteBySource()
    rs.rows_by_source["scan-0042"] = 2
    refs = FakeStoreWithDeleteBySource()
    refs.rows_by_source["scan-0042"] = 1

    out = await forget_source(
        "scan-0042",
        document_ingest_service=svc,
        record_store=rs,
        reference_store=refs,
    )
    assert out == {
        "chunks_deleted": 1,
        "records_deleted": 2,
        "references_deleted": 1,
    }
    assert not store.rows
    assert "scan-0042" not in rs.rows_by_source
    assert "scan-0042" not in refs.rows_by_source


@pytest.mark.asyncio
async def test_forget_source_keyless_only_deletes_wired_tiers():
    """No document_ingest_service (keyless server) — records/references still
    get forgotten; chunks_deleted stays 0 rather than erroring."""
    rs = FakeStoreWithDeleteBySource()
    rs.rows_by_source["scan-0042"] = 3
    out = await forget_source(
        "scan-0042",
        document_ingest_service=None,
        record_store=rs,
        reference_store=None,
    )
    assert out == {"chunks_deleted": 0, "records_deleted": 3, "references_deleted": 0}


@pytest.mark.asyncio
async def test_forget_source_identity_links_dropped_persons_survive(tmp_path):
    """forget_source routes chunk deletion through delete_source, so its
    identity-link cascade (links dropped, persons/aliases survive) applies
    unchanged when reached via the cascade entry point."""
    from brainpalace_server.storage.identity_store import (
        Alias,
        IdentityStore,
        Link,
        Person,
    )

    idstore = IdentityStore(tmp_path / "identity.db")
    emb, store = FakeEmbedder(), FakeStorage()
    svc = DocumentIngestService(
        embedding_generator=emb, storage_backend=store, identity_store=idstore
    )
    source_id = "scan-0042"
    await svc.ingest_documents([_doc(source_id=source_id)])

    pid = idstore.upsert_person(Person(kind="person", domain="home"))
    idstore.upsert_alias(Alias(surface="Ivo", person_id=pid))
    idstore.add_link(
        Link(
            ref=f"{source_id}#0",
            ref_kind="chunk",
            role="speaker",
            method="user_asserted",
            at="2026-07-09T00:00:00Z",
            person_id=pid,
        )
    )

    out = await forget_source(source_id, document_ingest_service=svc)
    assert out["chunks_deleted"] >= 1
    assert idstore.links_for_person(pid) == []  # link gone
    assert idstore.get_person(pid) is not None  # person survives
    assert [c["person_id"] for c in idstore.resolve_candidates("Ivo")] == [pid]


@pytest.mark.asyncio
async def test_reingest_stale_marks_mention_link_and_delete_cascades_to_identity(
    tmp_path,
):
    """G5 Task 6: re-ingesting a source with edited text must stale-mark
    (never delete) the `mentioned` link addressing the changed chunk position,
    while a `speaker` link on the same position survives untouched. Then
    `delete_source` must drop both links but leave the person + its alias
    intact (they are user-asserted ground truth, not derived from text).

    Uses an underscore-bearing source_id (`msg_2026_07_09`) so a LIKE-pattern
    regression in the address predicate would fail this test (commit
    74cb05c6)."""
    from brainpalace_server.storage.identity_store import (
        Alias,
        IdentityStore,
        Link,
        Person,
    )

    idstore = IdentityStore(tmp_path / "identity.db")
    emb, store = FakeEmbedder(), FakeStorage()
    svc = DocumentIngestService(
        embedding_generator=emb, storage_backend=store, identity_store=idstore
    )

    source_id = "msg_2026_07_09"
    await svc.ingest_documents(
        [_doc(text="original message text", source_id=source_id)]
    )

    pid = idstore.upsert_person(Person(kind="person", domain="home"))
    idstore.upsert_alias(Alias(surface="Ivo", person_id=pid))
    speaker_link = idstore.add_link(
        Link(
            ref=f"{source_id}#0",
            ref_kind="chunk",
            role="speaker",
            method="user_asserted",
            at="2026-07-09T00:00:00Z",
            person_id=pid,
        )
    )
    mention_link = idstore.add_link(
        Link(
            ref=f"{source_id}#0",
            ref_kind="span",
            role="mentioned",
            method="alias_match",
            at="2026-07-09T00:00:00Z",
            person_id=pid,
        )
    )

    # Re-ingest the SAME source with EDITED text at chunk 0.
    await svc.ingest_documents(
        [_doc(text="edited message text now", source_id=source_id)]
    )

    links = {link.id: link for link in idstore.links_for_person(pid)}
    assert len(links) == 2  # nothing deleted
    assert links[speaker_link].stale == 0  # speaker link untouched
    assert links[mention_link].stale == 1  # mention link stale-marked

    await svc.delete_source(source_id)
    assert idstore.links_for_person(pid) == []  # both links gone
    assert idstore.get_person(pid) is not None  # person survives
    # alias survives — it still resolves the surface
    assert [c["person_id"] for c in idstore.resolve_candidates("Ivo")] == [pid]


class FakeBM25:
    def __init__(self):
        self.added: list[dict] = []
        self.removed: list[str] = []

    def add_chunks(self, entries):
        self.added.extend(entries)

    def remove_chunks(self, node_ids):
        self.removed.extend(node_ids)


@pytest.mark.asyncio
async def test_reingest_changed_text_removes_stale_chunks_from_bm25():
    emb, store, bm = FakeEmbedder(), FakeStorage(), FakeBM25()
    svc = DocumentIngestService(
        embedding_generator=emb, storage_backend=store, bm25_manager=bm
    )
    first = await svc.ingest_documents([_doc(text="stari tekst dokumenta")])
    stale_ids = set(first["chunk_ids"])
    out = await svc.ingest_documents([_doc(text="potpuno novi tekst dokumenta")])
    # Stale ids left both the vector store AND the bm25 corpus.
    assert out["chunks_deleted"] == len(stale_ids)
    assert stale_ids <= set(bm.removed)
    # The new chunk ids were never removed.
    assert not (set(out["chunk_ids"]) & set(bm.removed))


@pytest.mark.asyncio
async def test_reingest_bm25_corpus_reflects_only_new_chunk(tmp_path):
    from brainpalace_server.indexing.bm25_index import BM25IndexManager

    emb, store = FakeEmbedder(), FakeStorage()
    bm = BM25IndexManager(persist_dir=str(tmp_path))
    svc = DocumentIngestService(
        embedding_generator=emb, storage_backend=store, bm25_manager=bm
    )
    await svc.ingest_documents([_doc(text="stari tekst dokumenta")])
    await svc.ingest_documents([_doc(text="potpuno novi tekst dokumenta")])
    # Only the new chunk is in the bm25 corpus (stale one removed on re-ingest).
    assert bm.corpus_size == 1


class _FakeChunk:
    def __init__(self, text):
        self.text = text


class FakeChunker:
    """Splits any document into 3 fixed chunks, in order."""

    async def chunk_single_document(self, loaded):
        return [_FakeChunk(f"{loaded.text} part {i}") for i in range(3)]


@pytest.mark.asyncio
async def test_chunk_index_persisted_in_order():
    emb, store = FakeEmbedder(), FakeStorage()
    svc = DocumentIngestService(
        embedding_generator=emb, storage_backend=store, chunker=FakeChunker()
    )
    out = await svc.ingest_documents([_doc()])
    metas = [store.rows[cid]["metadata"] for cid in out["chunk_ids"]]
    assert [m["chunk_index"] for m in metas] == [0, 1, 2]


@pytest.mark.asyncio
async def test_chunk_index_reserved_key_collision_raises():
    svc, _, _ = _svc()
    with pytest.raises(ValueError, match="reserved"):
        await svc.ingest_documents([_doc(metadata={"chunk_index": "x"})])


@pytest.mark.asyncio
async def test_chunks_by_source_groups_and_orders_ids():
    svc, emb, store = _svc()
    doc_a = _doc(text="prvi dokument", source_id="a")
    doc_b = _doc(text="drugi dokument", source_id="b")
    out = await svc.ingest_documents([doc_a, doc_b])
    assert set(out["chunks_by_source"]) == {"a", "b"}
    # Each source's chunk ids are a subset of the flat chunk_ids list, in order.
    all_grouped = [cid for ids in out["chunks_by_source"].values() for cid in ids]
    assert sorted(all_grouped) == sorted(out["chunk_ids"])
    assert out["chunks_by_source"]["a"] == [
        cid
        for cid in out["chunk_ids"]
        if store.rows[cid]["metadata"]["source_id"] == "a"
    ]


@pytest.mark.asyncio
async def test_per_item_sensitivity_overrides_batch_default():
    svc, _, store = _svc()
    doc_a = _doc(text="prvi dokument", source_id="a", sensitivity="private")
    doc_b = _doc(text="drugi dokument", source_id="b")
    await svc.ingest_documents([doc_a, doc_b], sensitivity="normal")
    metas_by_source = {
        cid_meta["metadata"]["source_id"]: cid_meta["metadata"]
        for cid_meta in store.rows.values()
    }
    assert metas_by_source["a"]["sensitivity"] == "private"  # per-item wins
    assert metas_by_source["b"]["sensitivity"] == "normal"  # falls back to batch


@pytest.mark.asyncio
async def test_none_sensitivity_falls_back_to_batch_default():
    svc, _, store = _svc()
    doc = _doc(sensitivity=None)
    await svc.ingest_documents([doc], sensitivity="restricted")
    meta = next(iter(store.rows.values()))["metadata"]
    assert meta["sensitivity"] == "restricted"


@pytest.mark.asyncio
async def test_reingest_replace_preserves_per_chunk_sensitivity():
    svc, _, store = _svc()
    await svc.ingest_documents(
        [_doc(text="prva verzija teksta", sensitivity="private")],
        sensitivity="normal",
    )
    out = await svc.ingest_documents(
        [_doc(text="druga izmijenjena verzija", sensitivity="private")],
        sensitivity="normal",
    )
    assert out["chunks_deleted"] >= 1  # old chunk replaced, not appended
    meta = next(iter(store.rows.values()))["metadata"]
    assert meta["sensitivity"] == "private"  # per-chunk value survives replace


def test_reserved_keys_frozen():
    assert {
        "domain",
        "source",
        "source_id",
        "ingested_at",
        "sensitivity",
        "text_language",
        "source_type",
    } <= RESERVED_METADATA_KEYS
