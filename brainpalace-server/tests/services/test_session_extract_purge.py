"""§3 — session re-extraction purges the session's prior graph triplets."""

import pytest

from brainpalace_server.models.session_extract import SessionExtraction
from brainpalace_server.services.session_extract_service import (
    SessionExtractService,
)
from brainpalace_server.storage.graph_store import GraphStoreManager


class _Embedder:
    async def embed_chunks(self, chunks):
        return [[0.0] * 3 for _ in chunks]


class _Backend:
    is_initialized = True

    async def delete_by_metadata(self, filt):
        pass

    async def upsert_documents(self, ids, embeddings, documents, metadatas):
        pass


def _payload(sid, triplets):
    return SessionExtraction(
        session_id=sid,
        summary="did things",
        decisions=[],
        triplets=[{"subject": s, "relation": r, "object": o} for s, r, o in triplets],
    )


def _valid_edges(mgr):
    return {
        (r[0], r[1], r[2])
        for r in mgr._graph_store._conn.execute(
            "SELECT source_id, label, target_id FROM edges " "WHERE valid_until IS NULL"
        )
    }


@pytest.mark.asyncio
async def test_session_reextract_purges_stale(tmp_path):
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    svc = SessionExtractService()
    kw = {
        "embedder": _Embedder(),
        "storage_backend": _Backend(),
        "graph_store": mgr,
    }
    r1 = await svc.store(_payload("s1", [("session s1", "ran-in", "grep")]), **kw)
    assert r1.triplets_stored == 1
    edges = _valid_edges(mgr)
    assert any(o == "grep" for _, _, o in edges)
    # Shrinking triplet list: the stale fact must disappear.
    await svc.store(_payload("s1", [("session s1", "ran-in", "sed")]), **kw)
    edges = _valid_edges(mgr)
    assert any(o == "sed" for _, _, o in edges)
    assert not any(o == "grep" for _, _, o in edges)


@pytest.mark.asyncio
async def test_session_triplets_carry_domain_and_source(tmp_path):
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    await SessionExtractService().store(
        _payload("s2", [("session s2", "ran-in", "grep")]),
        embedder=_Embedder(),
        storage_backend=_Backend(),
        graph_store=mgr,
    )
    row = mgr._graph_store._conn.execute(
        "SELECT source_file FROM edges WHERE valid_until IS NULL"
    ).fetchone()
    assert row["source_file"] == "session:s2"
    doms = {r[0] for r in mgr._graph_store._conn.execute("SELECT domain FROM nodes")}
    assert doms == {"session"}
