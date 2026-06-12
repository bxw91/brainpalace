"""Tests for VectorStoreManager.compact_if_bloated — dead-row reclamation.

Every collection recreation (heal rebuild, reset, duplicate-server stomp)
strands the previous generation's ``embeddings``/``embedding_metadata`` rows in
``chroma.sqlite3`` as DEAD rows — invisible to the API but holding full chunk
text (the chunk-recovery fuel). After a few incidents the file holds several
full copies of the index and SQLite never shrinks. ``compact_if_bloated``
rebuilds the whole persist dir from the live collections (no re-embed, public
API only), swaps it in atomically, and deletes the bloat — but only when the
dead-row count crosses the threshold, so healthy stores pay nothing.
"""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path

import pytest

from brainpalace_server.storage.vector_store import VectorStoreManager

DIM = 8


def _emb(seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(DIM)]


async def _make_store(persist: Path, n: int) -> VectorStoreManager:
    store = VectorStoreManager(
        persist_dir=str(persist),
        collection_name="test_collection",
    )
    await store.initialize()
    if n:
        await store.upsert_documents(
            ids=[f"id_{i}" for i in range(n)],
            embeddings=[_emb(i) for i in range(n)],
            documents=[f"doc {i}" for i in range(n)],
            metadatas=[{"i": i} for i in range(n)],
        )
    return store


def _dead_live(persist: Path) -> tuple[int, int]:
    con = sqlite3.connect(f"file:{persist / 'chroma.sqlite3'}?mode=ro", uri=True)
    try:
        total = con.execute("SELECT count(*) FROM embeddings").fetchone()[0]
        live = con.execute(
            "SELECT count(*) FROM embeddings WHERE segment_id IN "
            "(SELECT id FROM segments)"
        ).fetchone()[0]
        return total - live, live
    finally:
        con.close()


def _strand_generation(store: VectorStoreManager, keep: int) -> None:
    """Recreate the collection keeping ``keep`` fresh docs — strands the old
    generation's rows as dead (exactly what a heal rebuild leaves behind)."""
    client = store._client
    assert client is not None
    client.delete_collection(store.collection_name)
    coll = client.create_collection(
        name=store.collection_name, metadata={"hnsw:space": "cosine"}
    )
    coll.add(
        ids=[f"new_{i}" for i in range(keep)],
        embeddings=[_emb(100 + i) for i in range(keep)],
        documents=[f"new doc {i}" for i in range(keep)],
        metadatas=[{"i": i} for i in range(keep)],
    )
    store._collection = coll


@pytest.mark.asyncio
async def test_compact_noop_when_not_bloated(tmp_path) -> None:
    persist = tmp_path / "data" / "chroma_db"
    store = await _make_store(persist, 10)

    result = await store.compact_if_bloated(min_dead=1)

    assert result is None  # no dead rows → nothing to do
    assert await store.get_count() == 10


@pytest.mark.asyncio
async def test_compact_noop_below_min_dead_threshold(tmp_path) -> None:
    persist = tmp_path / "data" / "chroma_db"
    store = await _make_store(persist, 10)
    _strand_generation(store, keep=5)  # 10 dead, 5 live

    result = await store.compact_if_bloated(min_dead=10_000)

    assert result is None  # below floor — healthy stores pay nothing
    dead, live = _dead_live(persist)
    assert dead == 10 and live == 5


@pytest.mark.asyncio
async def test_compact_reclaims_dead_rows_and_keeps_live_data(tmp_path) -> None:
    persist = tmp_path / "data" / "chroma_db"
    store = await _make_store(persist, 20)
    _strand_generation(store, keep=5)  # 20 dead, 5 live
    assert _dead_live(persist) == (20, 5)

    result = await store.compact_if_bloated(min_dead=1, dead_ratio=0.5)

    assert result is not None
    assert result["dead_rows_reclaimed"] == 20
    assert result["live_rows"] == 5
    # Same persist path, zero dead rows, live data intact and queryable.
    dead, live = _dead_live(persist)
    assert dead == 0 and live == 5
    assert await store.get_count() == 5
    got = await store.get_existing_ids([f"new_{i}" for i in range(5)])
    assert len(got) == 5
    # No temp dirs left behind.
    siblings = {p.name for p in persist.parent.iterdir()}
    assert siblings == {"chroma_db"}


@pytest.mark.asyncio
async def test_compact_preserves_other_collections(tmp_path) -> None:
    """The sqlite file is shared by ALL collections (e.g. brainpalace_memories)
    — compaction must carry every collection, not just this manager's."""
    persist = tmp_path / "data" / "chroma_db"
    store = await _make_store(persist, 10)
    other = store._client.create_collection(name="memories")
    other.add(
        ids=["m1", "m2"],
        embeddings=[_emb(1), _emb(2)],
        documents=["mem one", "mem two"],
        metadatas=[{"k": "v1"}, {"k": "v2"}],
    )
    _strand_generation(store, keep=3)

    result = await store.compact_if_bloated(min_dead=1, dead_ratio=0.5)

    assert result is not None
    assert await store.get_count() == 3
    kept = store._client.get_collection("memories")
    assert kept.count() == 2


@pytest.mark.asyncio
async def test_compact_writes_audit_event(tmp_path) -> None:
    """Persist dir is <state>/data/chroma_db → compact-events.jsonl lands in
    <state>/ next to heal-events.jsonl."""
    import json

    persist = tmp_path / "data" / "chroma_db"
    store = await _make_store(persist, 10)
    _strand_generation(store, keep=2)

    result = await store.compact_if_bloated(min_dead=1, dead_ratio=0.5)

    assert result is not None
    events_file = tmp_path / "compact-events.jsonl"
    assert events_file.exists()
    event = json.loads(events_file.read_text().strip().splitlines()[-1])
    assert event["dead_rows_reclaimed"] == 10
    assert event["live_rows"] == 2
