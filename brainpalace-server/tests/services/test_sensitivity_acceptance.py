"""Task 10 — end-to-end sensitivity acceptance (proof, not policy — D4).

One file proving the full contract from the SPEC's acceptance thought-experiment
across every data path: hidden by default, revealed by --include-sensitive,
aggregates exclude, propagation holds, the cache never leaks a revealed result
to a default caller, and the session-context PUSH surface never injects a
private memory.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.models.memory import Memory
from brainpalace_server.models.query import QueryMode, QueryRequest, QueryResult
from brainpalace_server.models.record import Record
from brainpalace_server.models.session_extract import (
    Decision,
    RecordItem,
    SessionExtraction,
    Triplet,
)
from brainpalace_server.services.memory_service import MemoryService
from brainpalace_server.services.query_cache import QueryCacheService
from brainpalace_server.services.query_service import QueryService
from brainpalace_server.services.session_context_service import SessionContextService
from brainpalace_server.services.session_extract_service import SessionExtractService
from brainpalace_server.storage.record_store import RecordStore
from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore

# ---------------------------------------------------------------------------
# Leg 1: compute record — hidden by default, revealed by flag, aggregate excludes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_private_record_hidden_from_compute_revealed_by_flag(tmp_path):
    store = RecordStore(str(tmp_path / "r.db"))
    store.insert_records(
        [
            Record(
                id="pub",
                subject="p",
                metric="cost",
                value=10.0,
                source="s",
                confidence=1.0,
            ),
            Record(
                id="sec",
                subject="p",
                metric="cost",
                value=5.0,
                source="s",
                confidence=1.0,
                sensitivity="private",
            ),
        ]
    )
    svc = QueryService.__new__(QueryService)
    svc.record_store = store

    hidden = await svc._execute_compute_query(
        QueryRequest(query="what is the total cost", mode=QueryMode.COMPUTE)
    )
    assert sum(r.value for r in hidden) == 10.0  # private row excluded from total

    revealed = await svc._execute_compute_query(
        QueryRequest(
            query="what is the total cost",
            mode=QueryMode.COMPUTE,
            include_sensitive=True,
        )
    )
    assert sum(r.value for r in revealed) == 15.0


# ---------------------------------------------------------------------------
# Leg 2: graph node — private node hidden from the timeline read path
# ---------------------------------------------------------------------------


def _insert_node(store, nid, name, sensitivity="normal"):
    store._conn.execute(
        "INSERT INTO nodes (id, name, label, properties, domain, sensitivity) "
        "VALUES (?, ?, 'Decision', '{}', 'code', ?)",
        (nid, name, sensitivity),
    )
    store._conn.commit()


def _insert_edge(store, sid, tid, label="touches"):
    store._conn.execute(
        "INSERT INTO edges (id, source_id, target_id, label, valid_from, valid_until) "
        "VALUES (?, ?, ?, ?, '2026-01-01', NULL)",
        (f"{sid}->{tid}", sid, tid, label),
    )
    store._conn.commit()


@pytest.mark.asyncio
async def test_private_graph_node_hidden_from_timeline_revealed_by_flag(tmp_path):
    graph = SQLitePropertyGraphStore(str(tmp_path / "g.db"))
    _insert_node(graph, "n1", "AuthSecret", sensitivity="private")
    _insert_node(graph, "n2", "AuthToken")
    _insert_edge(graph, "n1", "n2")

    svc = QueryService(storage_backend=None)
    svc.graph_index_manager = SimpleNamespace(graph_store=graph)

    # default-deny: search_nodes cannot resolve the private entity -> no timeline
    hidden = await svc._execute_timeline_query(
        QueryRequest(query="history of AuthSecret", mode=QueryMode.TIMELINE)
    )
    assert hidden == []

    # revealed: node resolves and its edge history comes back
    revealed = await svc._execute_timeline_query(
        QueryRequest(
            query="history of AuthSecret",
            mode=QueryMode.TIMELINE,
            include_sensitive=True,
        )
    )
    assert revealed and revealed[0].subject == "AuthSecret"


# ---------------------------------------------------------------------------
# Leg 3: session chunk — private session_turn hidden from bm25 search
# ---------------------------------------------------------------------------


async def _identity_memory_boost(request, response):
    return response


def _full_flow_svc(bm25_results):
    svc = QueryService.__new__(QueryService)
    svc.is_ready = lambda: True
    svc.query_cache = None
    storage_backend = MagicMock()
    storage_backend.get_count = AsyncMock(return_value=1)
    svc.storage_backend = storage_backend
    svc._execute_bm25_query = AsyncMock(return_value=bm25_results)
    svc._apply_memory_boost = _identity_memory_boost
    return svc


def _session_chunk(cid, text, sensitivity):
    return QueryResult(
        text=text,
        source="session",
        score=1.0,
        chunk_id=cid,
        source_type="session_turn",
        metadata={"sensitivity": sensitivity},
    )


@pytest.mark.asyncio
async def test_private_session_chunk_hidden_from_search_revealed_by_flag(monkeypatch):
    # Keep the unrelated session hard-off gate open (this repo's own config has
    # session vector indexing OFF, which would hide every session_turn chunk
    # regardless of sensitivity and mask what this test is checking).
    monkeypatch.setattr(
        "brainpalace_server.config.session_config.session_recall_flags",
        lambda: (True, True),
    )
    results = [
        _session_chunk("c1", "public turn", "normal"),
        _session_chunk("c2", "secret turn", "private"),
    ]
    svc = _full_flow_svc(results)
    hidden = await svc.execute_query(QueryRequest(query="x", mode=QueryMode.BM25))
    assert [r.chunk_id for r in hidden.results] == ["c1"]

    svc = _full_flow_svc(results)
    revealed = await svc.execute_query(
        QueryRequest(query="x", mode=QueryMode.BM25, include_sensitive=True)
    )
    assert {r.chunk_id for r in revealed.results} == {"c1", "c2"}


# ---------------------------------------------------------------------------
# Leg 4: curated memory — recall + use_memory boost both default-deny
# ---------------------------------------------------------------------------


class _FakeHit:
    def __init__(self, cid, text, score, sensitivity):
        self.chunk_id = cid
        self.text = text
        self.score = score
        self.metadata = {
            "memory_id": cid,
            "section": "Notes",
            "tags": "",
            "sensitivity": sensitivity,
        }


class _FakeEmbeddings:
    async def embed_query(self, query):
        return [0.0]


class _FakeVectorStore:
    def __init__(self, hits):
        self._hits = hits

    async def similarity_search(self, query_embedding, top_k, similarity_threshold):
        return self._hits


def _memory_service(tmp_path):
    hits = [
        _FakeHit("m1", "public memory", 0.9, "normal"),
        _FakeHit("m2", "secret memory", 0.9, "private"),
    ]
    return MemoryService(
        tmp_path / "MEM.md",
        vector_store=_FakeVectorStore(hits),
        embedding_generator=_FakeEmbeddings(),
    )


@pytest.mark.asyncio
async def test_private_memory_hidden_from_recall_and_boost(tmp_path, monkeypatch):
    ms = _memory_service(tmp_path)

    # recall pull
    denied, _ = await ms.recall("x", include_sensitive=False)
    assert {h.text for h in denied} == {"public memory"}
    revealed, _ = await ms.recall("x", include_sensitive=True)
    assert {h.text for h in revealed} == {"public memory", "secret memory"}

    # use_memory boost (query tail): keep the origin filter off so the boost's
    # only gate is sensitivity.
    monkeypatch.setattr(
        "brainpalace_server.config.session_config.session_recall_flags",
        lambda: (True, True),
    )
    svc = QueryService.__new__(QueryService)
    svc.memory_service = ms

    from brainpalace_server.models.query import QueryResponse

    base = QueryResponse(results=[], total_results=0, query_time_ms=0.0)
    boosted = await svc._apply_memory_boost(
        QueryRequest(query="x", mode=QueryMode.HYBRID), base
    )
    texts = {r.text for r in boosted.results}
    assert "public memory" in texts
    assert "secret memory" not in texts

    revealed_boost = await svc._apply_memory_boost(
        QueryRequest(query="x", mode=QueryMode.HYBRID, include_sensitive=True), base
    )
    assert "secret memory" in {r.text for r in revealed_boost.results}


# ---------------------------------------------------------------------------
# Leg 5: propagation — a private session yields private derivatives
# ---------------------------------------------------------------------------


class _PropEmbedder:
    async def embed_chunks(self, chunks):
        return [[0.0] for _ in chunks]


class _PropStorage:
    def __init__(self):
        self.metadatas: list[dict] = []

    async def delete_by_metadata(self, where):
        return None

    async def upsert_documents(self, ids, embeddings, documents, metadatas):
        self.metadatas.extend(metadatas)


class _PropGraph:
    def __init__(self):
        self.sensitivities: list[str] = []

    def add_triplet(self, subject, predicate, obj, sensitivity="normal", **kwargs):
        self.sensitivities.append(sensitivity)
        return True

    def get_node(self, node_id):
        return None

    def nodes_by_exact_name(self, name, **kwargs):
        return []


class _PropRecordStore:
    def __init__(self):
        self.records: list = []

    def replace_source(self, source_id, recs):
        self.records.extend(recs)
        return len(recs)


class _PropMemory:
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
    graph = _PropGraph()
    record_store = _PropRecordStore()
    memory = _PropMemory()
    storage = _PropStorage()

    await SessionExtractService().store(
        payload,
        embedder=_PropEmbedder(),
        storage_backend=storage,
        graph_store=graph,
        memory_service=memory,
        record_store=record_store,
        sensitivity="private",
    )

    assert graph.sensitivities and all(s == "private" for s in graph.sensitivities)
    assert record_store.records and all(
        r.sensitivity == "private" for r in record_store.records
    )
    assert memory.sensitivities and all(s == "private" for s in memory.sensitivities)
    assert storage.metadatas and all(
        m["sensitivity"] == "private" for m in storage.metadatas
    )


# ---------------------------------------------------------------------------
# Leg 6: cache boundary — a revealed response never leaks to a default caller
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revealed_result_does_not_leak_through_shared_cache(monkeypatch):
    # Same rationale as the leg-3 test: keep the session hard-off gate open so
    # only the sensitivity filter/cache-key boundary is under test.
    monkeypatch.setattr(
        "brainpalace_server.config.session_config.session_recall_flags",
        lambda: (True, True),
    )
    results = [
        _session_chunk("c1", "public turn", "normal"),
        _session_chunk("c2", "secret turn", "private"),
    ]
    svc = _full_flow_svc(results)
    svc.query_cache = QueryCacheService()

    revealed = await svc.execute_query(
        QueryRequest(query="x", mode=QueryMode.BM25, include_sensitive=True)
    )
    assert {r.chunk_id for r in revealed.results} == {"c1", "c2"}

    # a later DEFAULT (e.g. MCP) query for the same text must not hit the
    # revealed slot
    default = await svc.execute_query(QueryRequest(query="x", mode=QueryMode.BM25))
    assert [r.chunk_id for r in default.results] == ["c1"]


# ---------------------------------------------------------------------------
# Leg 7: session-context PUSH — private memory never injected at session start
# ---------------------------------------------------------------------------


class _FakeMemoryStore:
    def __init__(self, memories):
        self._memories = memories

    def load(self):
        return self._memories


def test_session_context_push_excludes_private_memory():
    normal = Memory(id="m1", text="public fact", origin="user")
    private = Memory(id="m2", text="secret fact", origin="user", sensitivity="private")
    svc = SessionContextService(memory_service=_FakeMemoryStore([normal, private]))
    ctx = svc.build(project_root="/proj")
    assert "public fact" in ctx.text
    assert "secret fact" not in ctx.text
    assert ctx.memory_count == 1
