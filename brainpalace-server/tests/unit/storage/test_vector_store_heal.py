"""Tests for VectorStoreManager.heal_if_corrupt — HNSW bloat self-heal.

A vector index whose HNSW segment accumulates orphaned element slots (from a
past duplicate-server write or heavy soft-delete churn) segfaults the process on
the next upsert's native resize. ``heal_if_corrupt`` detects the bloat from
segment metadata (crash-safe, file-only) and rebuilds a compact index from the
intact SQLite side without re-embedding.

The bloat *detector* (``_hnsw_physical_count``) is verified against a real
on-disk pickle below; the *rebuild* path is driven deterministically by
monkeypatching the detector, so these tests don't depend on ChromaDB's
sync/persist timing.
"""

import glob
import pickle
import random
import types
from pathlib import Path

import pytest

from brainpalace_server.storage.vector_store import VectorStoreManager

DIM = 8


def _emb(seed: int) -> list[float]:
    # Varied direction *and* magnitude per id so cosine distance (angle-only)
    # and squared-l2 (magnitude-sensitive) are clearly distinguishable — the
    # behavioral space probe needs that separation.
    rng = random.Random(seed)
    scale = 1.0 + seed
    return [rng.uniform(-1.0, 1.0) * scale for _ in range(DIM)]


async def _make_store(tmp_path, n: int) -> VectorStoreManager:
    """A persistent store seeded with ``n`` vectors."""
    store = VectorStoreManager(
        persist_dir=str(tmp_path / "chroma_db"),
        collection_name="test_collection",
    )
    await store.initialize()
    await store.upsert_documents(
        ids=[f"id_{i}" for i in range(n)],
        embeddings=[_emb(i) for i in range(n)],
        documents=[f"doc {i}" for i in range(n)],
        metadatas=[{"i": i} for i in range(n)],
    )
    return store


@pytest.mark.asyncio
async def test_physical_count_none_when_no_db(tmp_path) -> None:
    """Missing store yields None, never raises."""
    store = VectorStoreManager(
        persist_dir=str(tmp_path / "absent"),
        collection_name="test_collection",
    )
    assert store._hnsw_physical_count() is None


@pytest.mark.asyncio
async def test_physical_count_reads_pickle(tmp_path) -> None:
    """_hnsw_physical_count reads total_elements_added from the segment pickle."""
    store = await _make_store(tmp_path, 10)

    # Locate the persisted VECTOR segment dir and drop a metadata pickle with a
    # known counter (ChromaDB writes this on real sync/shutdown; we synthesize
    # it so the parser is tested without depending on that timing).
    seg_dirs = [
        Path(p).parent
        for p in glob.glob(str(Path(store.persist_dir) / "*" / "header.bin"))
    ]
    assert seg_dirs, "expected a persisted segment dir"
    fake = types.SimpleNamespace(total_elements_added=9999, id_to_label={})
    with open(seg_dirs[0] / "index_metadata.pickle", "wb") as fh:
        pickle.dump(fake, fh)

    assert store._hnsw_physical_count() == 9999


@pytest.mark.asyncio
async def test_heal_noop_on_empty(tmp_path) -> None:
    """An empty index needs no heal."""
    store = VectorStoreManager(
        persist_dir=str(tmp_path / "chroma_db"),
        collection_name="test_collection",
    )
    await store.initialize()
    assert await store.heal_if_corrupt() == 0


@pytest.mark.asyncio
async def test_heal_noop_when_not_bloated(tmp_path, monkeypatch) -> None:
    """Physical count near live count → no rebuild."""
    store = await _make_store(tmp_path, 20)
    monkeypatch.setattr(store, "_hnsw_physical_count", lambda: 20)
    assert await store.heal_if_corrupt() == 0
    assert await store.get_count() == 20


@pytest.mark.asyncio
async def test_heal_noop_when_physical_unknown(tmp_path, monkeypatch) -> None:
    """Unknown physical count (None) → leave the index alone."""
    store = await _make_store(tmp_path, 20)
    monkeypatch.setattr(store, "_hnsw_physical_count", lambda: None)
    assert await store.heal_if_corrupt() == 0
    assert await store.get_count() == 20


async def _make_l2_store(tmp_path, n: int) -> VectorStoreManager:
    """A persistent store whose collection is pinned to the wrong (l2) space."""
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    path = str(tmp_path / "chroma_db")
    client = chromadb.PersistentClient(
        path=path,
        settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
    )
    client.create_collection(name="test_collection", metadata={"hnsw:space": "l2"})
    del client

    store = VectorStoreManager(persist_dir=path, collection_name="test_collection")
    await store.initialize()  # get_or_create returns the existing l2 collection
    await store.upsert_documents(
        ids=[f"id_{i}" for i in range(n)],
        embeddings=[_emb(i) for i in range(n)],
        documents=[f"doc {i}" for i in range(n)],
        metadatas=[{"i": i} for i in range(n)],
    )
    return store


@pytest.mark.asyncio
async def test_measured_cosine_true_by_default(tmp_path) -> None:
    """VectorStoreManager-created collections actually score by cosine."""
    store = await _make_store(tmp_path, 6)
    assert store._measured_cosine() is True


@pytest.mark.asyncio
async def test_measured_cosine_false_on_l2(tmp_path) -> None:
    """An l2-pinned collection is detected as non-cosine."""
    store = await _make_l2_store(tmp_path, 6)
    assert store._measured_cosine() is False


@pytest.mark.asyncio
async def test_heal_noop_on_cosine(tmp_path, monkeypatch) -> None:
    """Cosine + not bloated → no rebuild."""
    store = await _make_store(tmp_path, 10)
    monkeypatch.setattr(store, "_hnsw_physical_count", lambda: 10)
    assert await store.heal_if_corrupt() == 0


@pytest.mark.asyncio
async def test_heal_fixes_wrong_space(tmp_path, monkeypatch) -> None:
    """An l2 collection is rebuilt onto cosine, preserving data — even when
    not bloated (space alone triggers the heal)."""
    store = await _make_l2_store(tmp_path, 12)
    assert store._measured_cosine() is False
    # Not bloated, so only the wrong space should drive the rebuild.
    monkeypatch.setattr(store, "_hnsw_physical_count", lambda: 12)

    recovered = await store.heal_if_corrupt()
    assert recovered == 12
    assert store._measured_cosine() is True
    assert await store.get_count() == 12
    for i in range(12):
        assert await store.get_by_id(f"id_{i}") is not None


@pytest.mark.asyncio
async def test_prune_removes_orphan_segment(tmp_path) -> None:
    """A segment dir absent from the segments table is removed; live kept."""
    store = await _make_store(tmp_path, 10)
    persist = Path(store.persist_dir)
    live_dirs = [Path(p).parent for p in glob.glob(str(persist / "*" / "header.bin"))]
    assert live_dirs

    orphan = persist / "00000000-0000-0000-0000-000000000000"
    orphan.mkdir()
    (orphan / "header.bin").write_bytes(b"stale")

    assert store._prune_orphan_segments() == 1
    assert not orphan.exists()
    for d in live_dirs:
        assert d.exists()


@pytest.mark.asyncio
async def test_prune_keeps_non_segment_dirs(tmp_path) -> None:
    """A folder without an HNSW header is never touched, even if unreferenced."""
    store = await _make_store(tmp_path, 5)
    keep = Path(store.persist_dir) / "not-a-segment"
    keep.mkdir()
    (keep / "foo.txt").write_text("x")

    assert store._prune_orphan_segments() == 0
    assert keep.exists()


@pytest.mark.asyncio
async def test_heal_rebuilds_when_bloated(tmp_path, monkeypatch) -> None:
    """A bloated index is compacted from SQLite, preserving all live data, and
    the upsert that used to segfault then succeeds."""
    store = await _make_store(tmp_path, 20)

    # Simulate the real corruption: physical element slots dwarf live vectors.
    monkeypatch.setattr(store, "_hnsw_physical_count", lambda: 13108)

    recovered = await store.heal_if_corrupt()
    assert recovered == 20

    # Live data fully preserved after the rebuild.
    assert await store.get_count() == 20
    for i in range(20):
        assert await store.get_by_id(f"id_{i}") is not None

    # The op that used to crash now works against the compact index.
    n = await store.upsert_documents(
        ids=[f"new_{i}" for i in range(10)],
        embeddings=[_emb(100 + i) for i in range(10)],
        documents=["x"] * 10,
        metadatas=[{"k": "v"}] * 10,
    )
    assert n == 10
    assert await store.get_count() == 30
