"""E2E validation: two-session supersession → invalidation + stale penalty.

Phases 060 (persist) + 090 (sqlite temporal) + 100 (typed nodes) + 140
(supersession + stale-decision penalty), composed through the REAL
SessionExtractService, GraphStoreManager(sqlite), and QueryService ranking —
keyless (fake embedder/store; real graph + real linking + real penalty).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.config import settings
from brainpalace_server.models.query import QueryResult
from brainpalace_server.models.session_extract import SessionExtraction
from brainpalace_server.services.query_service import QueryService
from brainpalace_server.services.session_extract_service import SessionExtractService
from brainpalace_server.storage.graph_store import GraphStoreManager


class FakeStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    async def delete_by_metadata(self, where):  # noqa: ANN001,ANN201
        sid, st = where.get("session_id"), where.get("source_type")
        for cid in [
            k
            for k, v in self.docs.items()
            if v["m"].get("session_id") == sid and v["m"].get("source_type") == st
        ]:
            del self.docs[cid]
        return 0

    async def upsert_documents(
        self, ids, embeddings, documents, metadatas
    ):  # noqa: ANN001,ANN201
        for cid, doc, meta in zip(ids, documents, metadatas):
            self.docs[cid] = {"text": doc, "m": meta}


class FakeEmbedder:
    async def embed_chunks(self, chunks, progress=None):  # noqa: ANN001,ANN201
        return [[0.0, 0.1] for _ in chunks]


class FakeMemory:
    def __init__(self) -> None:
        self.added: list[str] = []

    async def add(
        self, text, section="Project", tags=None, origin="user", confidence=1.0
    ):  # noqa: ANN001,ANN201,E501
        self.added.append(text)

    def load(self):
        return []


@pytest.fixture(autouse=True)
def _enable_graph(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    monkeypatch.setattr(settings, "BRAINPALACE_STALE_DECISION_PENALTY", 0.5)
    GraphStoreManager.reset_instance()
    yield
    GraphStoreManager.reset_instance()


def _graph(tmp_path: Path) -> GraphStoreManager:
    mgr = GraphStoreManager(persist_dir=tmp_path / "g", store_type="sqlite")
    mgr.initialize()
    return mgr


async def test_supersession_invalidates_facts_and_penalises(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    store, emb, mem = FakeStore(), FakeEmbedder(), FakeMemory()
    svc = SessionExtractService()

    # Session A: records a decision (via `decided`) — creates a Decision node
    # with a `decided` fact edge.
    a = SessionExtraction(
        session_id="A",
        summary="chose in-memory cache",
        decisions=[{"text": "use in-memory cache", "rationale": "simple"}],
        triplets=[
            {"subject": "A", "relation": "decided", "object": "use in-memory cache"}
        ],
    )
    await svc.store(
        a, embedder=emb, storage_backend=store, graph_store=graph, memory_service=mem
    )

    # Session B supersedes A's decision.
    b = SessionExtraction(
        session_id="B",
        summary="switched to Redis",
        decisions=[
            {
                "text": "use Redis cache",
                "rationale": "scale",
                "supersedes": "use in-memory cache",
            }
        ],
        triplets=[
            {
                "subject": "use in-memory cache",
                "relation": "superseded-by",
                "object": "use Redis cache",
            }
        ],
    )
    await svc.store(
        b, embedder=emb, storage_backend=store, graph_store=graph, memory_service=mem
    )

    # 140: the old decision's `decided` fact is invalidated; the supersedes
    # history edge is preserved.
    tl = graph.timeline("use in-memory cache")
    decided = [e for e in tl if e["predicate"] == "decided"]
    superseded = [e for e in tl if e["predicate"] == "superseded-by"]
    assert decided and decided[0]["valid"] is False
    assert superseded and superseded[0]["valid"] is True

    # 140: the stale decision is penalised at query time (real penalty path).
    svc_q = object.__new__(QueryService)  # type: ignore[call-arg]
    svc_q.graph_index_manager = type("GM", (), {"graph_store": graph})()
    results = [
        QueryResult(
            text="use in-memory cache",
            source="A",
            score=1.0,
            chunk_id="A",
            source_type="session_decision",
        ),
        QueryResult(
            text="use Redis cache",
            source="B",
            score=0.9,
            chunk_id="B",
            source_type="session_decision",
        ),
    ]
    ranked = svc_q._apply_stale_decision_penalty(results)
    assert ranked[0].chunk_id == "B"  # current decision now ranks first
    by_id = {r.chunk_id: r.score for r in ranked}
    assert by_id["A"] == pytest.approx(0.5)  # stale halved
