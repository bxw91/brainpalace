"""G5 Task 8: person-filtered retrieval + A5 sensitivity over a REAL
IdentityStore on a temp db and a fake storage backend. Asserts the behavior,
not the structure: a sensitive person's chunks are absent by default and
present only via the existing include-sensitive switch."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from brainpalace_server.services.query_service import QueryService
from brainpalace_server.storage.identity_store import IdentityStore, Link, Person


class FakeStorage:
    """Metadata store keyed by chunk id; resolves the source_id/chunk_index
    where-clauses that chunk_ids_for_person issues. Carries vector_store /
    bm25_manager attributes (None) so QueryService.__init__ takes them as-is
    instead of calling the heavy global getters."""

    vector_store = None
    bm25_manager = None

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def add(self, chunk_id: str, source_id: str, chunk_index: int) -> None:
        self.rows[chunk_id] = {"source_id": source_id, "chunk_index": chunk_index}

    async def get_ids_by_where(self, where: dict) -> set[str]:
        conds = where.get("$and", [where])
        out = set()
        for cid, meta in self.rows.items():
            if all(meta.get(k) == v for c in conds for k, v in c.items()):
                out.add(cid)
        return out


def _build(tmp_path):
    store = IdentityStore(tmp_path / "identity.db")
    storage = FakeStorage()
    svc = QueryService(
        storage_backend=storage,
        embedding_generator=SimpleNamespace(),
        graph_index_manager=SimpleNamespace(),
        identity_store=store,
    )
    return svc, store, storage


def _speaker_link(store, pid, ref):
    store.add_link(
        Link(
            ref=ref,
            ref_kind="chunk",
            role="speaker",
            method="user_asserted",
            at="2026-07-09T00:00:00Z",
            person_id=pid,
        )
    )


@pytest.mark.asyncio
async def test_person_filter_resolves_to_chunk_ids(tmp_path):
    svc, store, storage = _build(tmp_path)
    pid = store.upsert_person(Person(kind="person", domain="home", name="Ana"))
    storage.add("c0", "msg_1", 0)
    _speaker_link(store, pid, "msg_1#0")

    ids = await svc.chunk_ids_for_person(pid)
    assert ids == ["c0"]


@pytest.mark.asyncio
async def test_sensitive_person_hidden_by_default_and_shown_when_included(tmp_path):
    svc, store, storage = _build(tmp_path)
    secret = store.upsert_person(
        Person(kind="person", domain="home", name="Mole", sensitivity="private")
    )
    storage.add("c1", "msg_2", 0)
    _speaker_link(store, secret, "msg_2#0")

    # A5: absent by default (same include-sensitive switch as chunk-level).
    assert await svc.chunk_ids_for_person(secret) == []
    # Present only via the existing include-sensitive path.
    assert await svc.chunk_ids_for_person(secret, include_sensitive=True) == ["c1"]


@pytest.mark.asyncio
async def test_grouping_buckets_unresolved_and_hides_sensitive(tmp_path):
    svc, store, storage = _build(tmp_path)
    ana = store.upsert_person(Person(kind="person", domain="home", name="Ana"))
    secret = store.upsert_person(
        Person(kind="person", domain="home", name="Mole", sensitivity="private")
    )
    _speaker_link(store, ana, "msg_1#0")
    _speaker_link(store, secret, "msg_2#0")

    r_ana = SimpleNamespace(
        chunk_id="c0", metadata={"source_id": "msg_1", "chunk_index": 0}
    )
    r_secret = SimpleNamespace(
        chunk_id="c1", metadata={"source_id": "msg_2", "chunk_index": 0}
    )
    r_orphan = SimpleNamespace(
        chunk_id="c2", metadata={"source_id": "msg_9", "chunk_index": 0}
    )

    grouped = svc.group_results_by_person([r_ana, r_secret, r_orphan])
    assert grouped["by_person"] == {ana: [r_ana]}  # secret not attributed by default
    assert grouped["unresolved"] == [r_secret, r_orphan]  # secret falls to unresolved

    grouped2 = svc.group_results_by_person(
        [r_ana, r_secret, r_orphan], include_sensitive=True
    )
    assert grouped2["by_person"] == {ana: [r_ana], secret: [r_secret]}
    assert grouped2["unresolved"] == [r_orphan]
