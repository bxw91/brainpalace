"""Phase 060 — SessionExtractService persistence + idempotency."""

from __future__ import annotations

from pathlib import Path

from brainpalace_server.models.session_extract import SessionExtraction
from brainpalace_server.services.session_extract_service import SessionExtractService


class FakeStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.deletes: list[dict] = []

    async def delete_by_metadata(self, where):  # noqa: ANN001,ANN201
        self.deletes.append(where)
        st = where.get("source_type")
        sid = where.get("session_id")
        for cid in [
            k
            for k, v in self.docs.items()
            if v["meta"].get("session_id") == sid and v["meta"].get("source_type") == st
        ]:
            del self.docs[cid]
        return 0

    async def upsert_documents(
        self, ids, embeddings, documents, metadatas
    ):  # noqa: ANN001,ANN201
        for cid, doc, meta in zip(ids, documents, metadatas):
            self.docs[cid] = {"text": doc, "meta": meta}


class FakeEmbedder:
    async def embed_chunks(self, chunks, progress=None):  # noqa: ANN001,ANN201
        return [[0.0, 0.1] for _ in chunks]


class FakeGraph:
    def __init__(self) -> None:
        self.triplets: list[tuple] = []
        self.typed: list[tuple] = []

    def add_triplet(  # noqa: ANN001,ANN201
        self,
        subject,
        predicate,
        obj,
        subject_type=None,
        object_type=None,
        source_chunk_id=None,
        source_file=None,
        domain="code",
    ):
        self.triplets.append((subject, predicate, obj))
        self.typed.append((subject_type, predicate, object_type))
        return True

    def invalidate_by_source_file(
        self, source_file, domain="code"
    ):  # noqa: ANN001,ANN201
        return 0

    def sweep_orphan_nodes(self, domain="code"):  # noqa: ANN001,ANN201
        return 0


def _payload(decisions: int = 2) -> SessionExtraction:
    return SessionExtraction(
        session_id="s1",
        summary="did the thing",
        decisions=[
            {"text": f"decision {i}", "files": [f"f{i}.py"]} for i in range(decisions)
        ],
        triplets=[{"subject": "f0.py", "relation": "touches", "object": "thing"}],
    )


async def test_store_writes_summary_and_decision_chunks() -> None:
    store, emb = FakeStore(), FakeEmbedder()
    res = await SessionExtractService().store(
        _payload(2), embedder=emb, storage_backend=store
    )
    assert res.summary_chunks == 1
    assert res.decision_chunks == 2
    types = sorted(v["meta"]["source_type"] for v in store.docs.values())
    assert types == ["session_decision", "session_decision", "session_summary"]


async def test_resubmit_is_idempotent_no_duplicates() -> None:
    store, emb = FakeStore(), FakeEmbedder()
    svc = SessionExtractService()
    await svc.store(_payload(3), embedder=emb, storage_backend=store)
    await svc.store(_payload(2), embedder=emb, storage_backend=store)  # shrank
    # 1 summary + 2 decisions = 3 (the 3rd from the first submit was purged).
    assert len(store.docs) == 3
    decisions = [
        v for v in store.docs.values() if v["meta"]["source_type"] == "session_decision"
    ]
    assert len(decisions) == 2


async def test_triplets_stored_when_graph_present() -> None:
    store, emb, graph = FakeStore(), FakeEmbedder(), FakeGraph()
    res = await SessionExtractService().store(
        _payload(1), embedder=emb, storage_backend=store, graph_store=graph
    )
    assert res.triplets_stored == 1
    assert graph.triplets[0] == ("f0.py", "touches", "thing")
    # touches -> (File, None): subject typed File, object left untyped
    assert graph.typed[0] == ("File", "touches", None)


async def test_triplets_get_session_entity_types() -> None:
    """Phase 100: node types are derived from the relation, server-side."""
    store, emb, graph = FakeStore(), FakeEmbedder(), FakeGraph()
    payload = SessionExtraction(
        session_id="s1",
        summary="typed graph",
        decisions=[{"text": "d", "files": ["a.py"]}],
        triplets=[
            {"subject": "login 500", "relation": "fixed-by", "object": "token patch"},
            {"subject": "old plan", "relation": "superseded-by", "object": "new plan"},
            {"subject": "Bash", "relation": "ran-in", "object": "s1"},
        ],
    )
    await SessionExtractService().store(
        payload, embedder=emb, storage_backend=store, graph_store=graph
    )
    assert ("Error", "fixed-by", "Decision") in graph.typed
    assert ("Decision", "superseded-by", "Decision") in graph.typed
    assert ("Tool", "ran-in", "Session") in graph.typed


async def test_graph_absent_is_noop() -> None:
    store, emb = FakeStore(), FakeEmbedder()
    res = await SessionExtractService().store(
        _payload(1), embedder=emb, storage_backend=store, graph_store=None
    )
    assert res.triplets_stored == 0


async def test_decisions_digest_written_and_idempotent(tmp_path: Path) -> None:
    store, emb = FakeStore(), FakeEmbedder()
    svc = SessionExtractService()
    digest = tmp_path / "BRAINPALACE_DECISIONS.md"
    await svc.store(
        _payload(2), embedder=emb, storage_backend=store, digest_path=digest
    )
    text1 = digest.read_text()
    assert "## Session `s1`" in text1
    assert text1.count("<!-- session:s1 -->") == 1
    # Re-submit → block rewritten, not duplicated.
    await svc.store(
        _payload(1), embedder=emb, storage_backend=store, digest_path=digest
    )
    text2 = digest.read_text()
    assert text2.count("<!-- session:s1 -->") == 1
    assert text2.count("- decision 0") == 1
    assert "- decision 1" not in text2  # shrank to 1 decision
