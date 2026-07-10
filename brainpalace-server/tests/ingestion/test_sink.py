from collections.abc import Iterable
from typing import Any

import pytest

from brainpalace_server.ingestion.adapter import (
    EmittedDocument,
    EmittedEntity,
    EmittedRecord,
    EmittedReference,
    reset_adapters,
)
from brainpalace_server.ingestion.sink import ProvenanceError, aingest, ingest
from brainpalace_server.models.domains import register_domain
from brainpalace_server.models.record import RecordCandidate
from brainpalace_server.storage.record_store import RecordStore
from brainpalace_server.storage.reference_catalog_store import ReferenceCatalogStore

TS = "2026-07-05T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _clean():
    reset_adapters()
    yield
    reset_adapters()


class _RecAdapter:
    domain = "code"
    source = "unit"

    def __init__(self, items):
        self._items = items

    def emit(self, payload: Any) -> Iterable[Any]:
        return iter(self._items)


def _rec(**kw):
    return EmittedRecord(
        candidate=RecordCandidate(subject="s", metric="m", value=1.0),
        id=kw.get("id", "r1"),
        domain=kw.get("domain", "code"),
        source=kw.get("source", "unit"),
        source_id=kw.get("source_id", "sid"),
        confidence=kw.get("confidence", 0.7),
        properties=kw.get("properties", {}),
    )


def test_eager_record_lands_in_record_store(tmp_path):
    rs = RecordStore(tmp_path / "records.db")
    counts = ingest(_RecAdapter([_rec()]), None, record_store=rs, ingested_at=TS)
    assert counts["records"] == 1
    # id/confidence preserved from EmittedRecord; ingested_at stamped by sink
    row = rs._conn.execute(
        "SELECT id,confidence,ingested_at,salience FROM records WHERE id='r1'"
    ).fetchone()
    assert row[0] == "r1"
    assert row[1] == 0.7
    assert row[2] == TS
    assert row[3] >= 0.0  # salience computed by sink


def test_lazy_reference_lands_in_reference_store(tmp_path):
    rs = RecordStore(tmp_path / "records.db")
    refs = ReferenceCatalogStore(tmp_path / "refs.db")
    register_domain("code")

    class _RefAdapter:
        domain = "code"
        source = "unit"

        def emit(self, payload):
            yield EmittedReference(
                pointer="p://1",
                summary="s",
                domain="code",
                source="unit",
                source_id="sid",
            )

    counts = ingest(
        _RefAdapter(), None, record_store=rs, reference_store=refs, ingested_at=TS
    )
    assert counts["references"] == 1
    assert refs.count() == 1


def test_unknown_domain_rejected(tmp_path):
    rs = RecordStore(tmp_path / "records.db")
    with pytest.raises(ProvenanceError):
        ingest(
            _RecAdapter([_rec(domain="not-registered-xyz")]),
            None,
            record_store=rs,
            ingested_at=TS,
        )


def test_missing_source_id_rejected(tmp_path):
    rs = RecordStore(tmp_path / "records.db")
    with pytest.raises(ProvenanceError):
        ingest(_RecAdapter([_rec(source_id="")]), None, record_store=rs, ingested_at=TS)


def test_sync_document_points_at_the_async_seam(tmp_path):
    # Documents ARE routed — by aingest. The sync error must say so, not claim
    # the tier is unimplemented, or a caller abandons a feature that exists.
    rs = RecordStore(tmp_path / "records.db")
    register_domain("code")

    class _DocAdapter:
        domain = "code"
        source = "unit"

        def emit(self, payload):
            yield EmittedDocument(
                text="x", metadata={}, domain="code", source="unit", source_id="sid"
            )

    with pytest.raises(NotImplementedError, match="async-only.*aingest"):
        ingest(_DocAdapter(), None, record_store=rs, ingested_at=TS)


def test_sync_entity_not_routed(tmp_path):
    rs = RecordStore(tmp_path / "records.db")
    register_domain("code")

    class _EntAdapter:
        domain = "code"
        source = "unit"

        def emit(self, payload):
            yield EmittedEntity(
                name="Ivan",
                kind="person",
                domain="code",
                source="unit",
                source_id="sid",
            )

    with pytest.raises(NotImplementedError, match="Phase 9"):
        ingest(_EntAdapter(), None, record_store=rs, ingested_at=TS)


def test_reject_is_atomic_nothing_written(tmp_path):
    # A valid eager item followed by an invalid one must write NOTHING —
    # the sink accumulates then writes after the drain completes.
    rs = RecordStore(tmp_path / "records.db")
    items = [_rec(id="ok"), _rec(id="bad", domain="not-registered-xyz")]
    with pytest.raises(ProvenanceError):
        ingest(_RecAdapter(items), None, record_store=rs, ingested_at=TS)
    assert rs._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0


def test_properties_pass_through(tmp_path):
    rs = RecordStore(tmp_path / "records.db")
    ingest(
        _RecAdapter([_rec(id="p", properties={"tier": "gold"})]),
        None,
        record_store=rs,
        ingested_at=TS,
    )
    row = rs._conn.execute("SELECT properties FROM records WHERE id='p'").fetchone()
    assert row[0] == '{"tier": "gold"}'


# --- Async sink: aingest routes EmittedDocument (Task 3) -------------------


class _DocAdapter:
    domain = "home"
    source = "scanner"

    def __init__(self, items):
        self._items = items

    def emit(self, payload):
        return list(self._items)


class _FakeIngestor:
    def __init__(self):
        self.calls = []

    async def ingest_documents(
        self, docs, *, sensitivity="normal", language=None, ingested_at=None
    ):
        self.calls.append((docs, sensitivity, ingested_at))
        chunks_by_source: dict[str, list[str]] = {}
        for i, d in enumerate(docs):
            chunks_by_source.setdefault(d.source_id, []).append(f"chunk-{i}")
        return {
            "chunks_new": len(docs),
            "chunks_kept": 0,
            "chunks_deleted": 0,
            "chunk_ids": [cid for ids in chunks_by_source.values() for cid in ids],
            "source_ids": sorted(chunks_by_source),
            "chunks_by_source": chunks_by_source,
        }


@pytest.mark.asyncio
async def test_aingest_routes_documents(tmp_path):
    register_domain("home")
    rs = RecordStore(tmp_path / "records.db")
    ingestor = _FakeIngestor()
    doc = EmittedDocument(
        text="ugovor", domain="home", source="scanner", source_id="s1"
    )
    counts = await aingest(
        _DocAdapter([doc]),
        None,
        record_store=rs,
        document_ingestor=ingestor,
        ingested_at="2026-07-06T00:00:00Z",
        sensitivity="private",
    )
    assert counts["documents"] == 1
    docs, sens, stamp = ingestor.calls[0]
    assert sens == "private" and stamp == "2026-07-06T00:00:00Z"
    assert docs[0].source_id == "s1"


@pytest.mark.asyncio
async def test_aingest_returns_chunks_grouped_by_source(tmp_path):
    register_domain("home")
    rs = RecordStore(tmp_path / "records.db")
    ingestor = _FakeIngestor()
    doc1 = EmittedDocument(
        text="ugovor", domain="home", source="scanner", source_id="s1"
    )
    doc2 = EmittedDocument(
        text="racun", domain="home", source="scanner", source_id="s2"
    )
    counts = await aingest(
        _DocAdapter([doc1, doc2]),
        None,
        record_store=rs,
        document_ingestor=ingestor,
        ingested_at="2026-07-06T00:00:00Z",
    )
    # Old count keys are unchanged (backward compatibility).
    assert counts["documents"] == 2
    assert counts["records"] == 0 and counts["references"] == 0
    # New: each source maps to its own ordered chunk ids.
    by_source = counts["documents_by_source"]
    assert set(by_source) == {"s1", "s2"}
    assert by_source["s1"] == ["chunk-0"]
    assert by_source["s2"] == ["chunk-1"]


@pytest.mark.asyncio
async def test_aingest_forwards_per_item_sensitivity_to_ingest_doc(tmp_path):
    """D6: EmittedDocument.sensitivity is an optional per-item override,
    forwarded verbatim into the IngestDoc the sink constructs — independent
    of the batch-level `sensitivity` kwarg passed to aingest."""
    register_domain("home")
    rs = RecordStore(tmp_path / "records.db")
    ingestor = _FakeIngestor()
    doc = EmittedDocument(
        text="ugovor",
        domain="home",
        source="scanner",
        source_id="s1",
        sensitivity="restricted",
    )
    await aingest(
        _DocAdapter([doc]),
        None,
        record_store=rs,
        document_ingestor=ingestor,
        ingested_at="2026-07-06T00:00:00Z",
        sensitivity="normal",
    )
    docs, _, _ = ingestor.calls[0]
    assert docs[0].sensitivity == "restricted"


@pytest.mark.asyncio
async def test_aingest_document_without_ingestor_is_hard_error(tmp_path):
    register_domain("home")
    rs = RecordStore(tmp_path / "records.db")
    doc = EmittedDocument(text="x", domain="home", source="scanner", source_id="s1")
    with pytest.raises(ProvenanceError, match="document_ingestor"):
        await aingest(
            _DocAdapter([doc]),
            None,
            record_store=rs,
            ingested_at="2026-07-06T00:00:00Z",
        )


@pytest.mark.asyncio
async def test_aingest_entity_without_identity_store_is_hard_error(tmp_path):
    # No longer NotImplementedError on the async seam — it mirrors the
    # document_ingestor branch: a ProvenanceError when the store is absent.
    register_domain("home")
    rs = RecordStore(tmp_path / "records.db")
    ent = EmittedEntity(
        name="Marko", kind="person", domain="home", source="scanner", source_id="s1"
    )
    with pytest.raises(ProvenanceError, match="identity_store"):
        await aingest(
            _DocAdapter([ent]),
            None,
            record_store=rs,
            ingested_at="2026-07-06T00:00:00Z",
        )


@pytest.mark.asyncio
async def test_aingest_entity_lands_person_aliases_and_external_link(tmp_path):
    from brainpalace_server.storage.identity_store import IdentityStore

    register_domain("home")
    rs = RecordStore(tmp_path / "records.db")
    store = IdentityStore(tmp_path / "identity.db")
    ent = EmittedEntity(
        name="Ivan",
        kind="person",
        domain="home",
        source="scanner",
        source_id="s1",
        aliases=["Ivo", "Ivica"],
        external_ref="voice-cluster-3",
    )
    counts = await aingest(
        _DocAdapter([ent]),
        None,
        record_store=rs,
        identity_store=store,
        ingested_at="2026-07-06T00:00:00Z",
        sensitivity="private",
    )
    assert counts["entities"] == 1
    # Existing keys unchanged.
    assert counts["records"] == 0 and counts["documents"] == 0
    # One person landed, sensitivity inherited from the call.
    assert store.count() == 1
    persons = store._conn.execute("SELECT id,name,sensitivity FROM person").fetchall()
    assert len(persons) == 1
    person_id, name, sensitivity = persons[0]
    assert name == "Ivan" and sensitivity == "private"
    # Two aliases, global scope (scope IS NULL).
    aliases = store._conn.execute(
        "SELECT surface,scope FROM alias WHERE person_id=?", (person_id,)
    ).fetchall()
    assert sorted(s for s, _ in aliases) == ["Ivica", "Ivo"]
    assert all(scope is None for _, scope in aliases)
    # One external-key link bound to the person.
    links = store.links_for_person(person_id)
    assert len(links) == 1
    assert links[0].ref == "voice-cluster-3" and links[0].ref_kind == "external"


@pytest.mark.asyncio
async def test_aingest_entity_without_external_ref_writes_no_link(tmp_path):
    from brainpalace_server.storage.identity_store import IdentityStore

    register_domain("home")
    rs = RecordStore(tmp_path / "records.db")
    store = IdentityStore(tmp_path / "identity.db")
    ent = EmittedEntity(
        name="Ana", kind="person", domain="home", source="scanner", source_id="s1"
    )
    counts = await aingest(
        _DocAdapter([ent]),
        None,
        record_store=rs,
        identity_store=store,
        ingested_at="2026-07-06T00:00:00Z",
    )
    assert counts["entities"] == 1
    person_id = store._conn.execute("SELECT id FROM person").fetchone()[0]
    assert store.links_for_person(person_id) == []


def test_sync_entity_still_raises_not_implemented(tmp_path):
    # The sync seam is unchanged: entities remain async-only (Phase 9 message).
    rs = RecordStore(tmp_path / "records.db")
    register_domain("home")

    class _Ent:
        domain = "home"
        source = "scanner"

        def emit(self, payload):
            yield EmittedEntity(
                name="Marko",
                kind="person",
                domain="home",
                source="scanner",
                source_id="s1",
            )

    with pytest.raises(NotImplementedError, match="Phase 9"):
        ingest(_Ent(), None, record_store=rs, ingested_at=TS)


class _FakeEmbedder:
    """embed_chunks protocol: reads `.text` off each item (mirrors
    DocumentIngestService's usage of the embedding generator)."""

    def __init__(self):
        self.calls = []

    async def embed_chunks(self, items):
        self.calls.append(list(items))
        return [[float(i)] for i, _ in enumerate(items)]


class _RefAdapter:
    domain = "code"
    source = "unit"

    def __init__(self, items):
        self._items = items

    def emit(self, payload):
        return list(self._items)


def _ref(**kw):
    return EmittedReference(
        pointer=kw.get("pointer", "p://1"),
        summary=kw.get("summary", "s"),
        domain=kw.get("domain", "code"),
        source=kw.get("source", "unit"),
        source_id=kw.get("source_id", "sid"),
    )


@pytest.mark.asyncio
async def test_aingest_with_reference_embedder_attaches_embeddings(tmp_path):
    register_domain("code")
    rs = RecordStore(tmp_path / "records.db")
    refs = ReferenceCatalogStore(tmp_path / "refs.db")
    embedder = _FakeEmbedder()

    counts = await aingest(
        _RefAdapter([_ref(pointer="p1"), _ref(pointer="p2")]),
        None,
        record_store=rs,
        reference_store=refs,
        reference_embedder=embedder,
        ingested_at=TS,
    )
    assert counts["references"] == 2
    assert refs.count_unembedded() == 0


@pytest.mark.asyncio
async def test_aingest_without_reference_embedder_degrades_gracefully(tmp_path):
    register_domain("code")
    rs = RecordStore(tmp_path / "records.db")
    refs = ReferenceCatalogStore(tmp_path / "refs.db")

    counts = await aingest(
        _RefAdapter([_ref(pointer="p1")]),
        None,
        record_store=rs,
        reference_store=refs,
        ingested_at=TS,
    )
    assert counts["references"] == 1
    assert refs.count() == 1
    assert refs.count_unembedded() == 1


@pytest.mark.asyncio
async def test_aingest_records_unchanged_from_sync(tmp_path):
    # Records/references route exactly like ingest(): the async path is the
    # same accumulate-then-replace_source logic.
    register_domain("code")
    rs = RecordStore(tmp_path / "records.db")
    counts = await aingest(
        _RecAdapter([_rec()]),
        None,
        record_store=rs,
        ingested_at=TS,
    )
    assert counts["records"] == 1 and counts["documents"] == 0
    row = rs._conn.execute(
        "SELECT id,confidence,ingested_at FROM records WHERE id='r1'"
    ).fetchone()
    assert row[0] == "r1" and row[1] == 0.7 and row[2] == TS
