from __future__ import annotations

import pytest

from brainpalace_server.models.session_extract import (
    Decision,
    RecordItem,
    SessionExtraction,
    Triplet,
)
from brainpalace_server.services.session_extract_service import SessionExtractService


class _FakeEmbedder:
    async def embed_chunks(self, chunks):
        return [[0.0] for _ in chunks]


class _FakeStorage:
    def __init__(self):
        self.metadatas: list[dict] = []

    async def delete_by_metadata(self, where):
        return None

    async def upsert_documents(self, ids, embeddings, documents, metadatas):
        self.metadatas.extend(metadatas)


class _FakeGraph:
    def __init__(self):
        self.sensitivities: list[str] = []

    def add_triplet(self, subject, predicate, obj, sensitivity="normal", **kwargs):
        self.sensitivities.append(sensitivity)
        return True

    # duck-typed by entity_resolver; degrade to "no match"
    def get_node(self, node_id):
        return None

    def nodes_by_exact_name(self, name, **kwargs):
        return []


class _FakeRecordStore:
    def __init__(self):
        self.records: list = []

    def replace_source(self, source_id, recs):
        self.records.extend(recs)
        return len(recs)


class _FakeMemory:
    def __init__(self):
        self.sensitivities: list[str] = []

    async def add(self, text, tags=None, origin="user", sensitivity="normal", **kw):
        self.sensitivities.append(sensitivity)
        return None

    def load(self):
        return []


@pytest.mark.asyncio
async def test_private_session_propagates_to_all_derivatives():
    payload = SessionExtraction(
        session_id="sess-priv",
        summary="did private stuff",
        decisions=[Decision(text="use approach X", rationale="it is faster")],
        records=[RecordItem(subject="proj", metric="cost", value=5.0)],
        triplets=[Triplet(subject="taskA", relation="depends-on", object="taskB")],
    )
    embedder = _FakeEmbedder()
    storage = _FakeStorage()
    graph = _FakeGraph()
    record_store = _FakeRecordStore()
    memory = _FakeMemory()

    svc = SessionExtractService()
    await svc.store(
        payload,
        embedder=embedder,
        storage_backend=storage,
        graph_store=graph,
        memory_service=memory,
        record_store=record_store,
        sensitivity="private",
    )

    # graph triplets inherit the source session's sensitivity
    assert graph.sensitivities and all(s == "private" for s in graph.sensitivities)
    # derived records inherit it
    assert record_store.records and all(
        r.sensitivity == "private" for r in record_store.records
    )
    # promoted curated memories inherit it
    assert memory.sensitivities and all(s == "private" for s in memory.sensitivities)
    # summary/decision chunks carry it too
    assert storage.metadatas and all(
        m["sensitivity"] == "private" for m in storage.metadatas
    )


@pytest.mark.asyncio
async def test_normal_session_stays_normal():
    payload = SessionExtraction(
        session_id="sess-pub",
        summary="did public stuff",
        records=[RecordItem(subject="proj", metric="cost", value=5.0)],
    )
    record_store = _FakeRecordStore()
    svc = SessionExtractService()
    await svc.store(
        payload,
        embedder=_FakeEmbedder(),
        storage_backend=_FakeStorage(),
        record_store=record_store,
    )
    assert record_store.records and all(
        r.sensitivity == "normal" for r in record_store.records
    )
