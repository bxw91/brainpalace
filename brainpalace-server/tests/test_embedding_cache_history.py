"""Hit-rate history snapshots on the embedding cache (dashboard plan 04)."""

import time

import aiosqlite
import pytest

from brainpalace_server.services.embedding_cache import (
    STATS_HISTORY_RETENTION_S,
    EmbeddingCacheService,
)


@pytest.mark.asyncio
async def test_snapshot_and_read_history(tmp_path):
    cache = EmbeddingCacheService(db_path=tmp_path / "embeddings.db")
    await cache.initialize(provider_fingerprint="t")
    wrote = await cache.maybe_snapshot(min_interval_s=0.0)
    assert wrote is True
    rows = await cache.get_stats_history()
    assert len(rows) == 1
    assert set(rows[0]) == {"ts", "hits", "misses", "entry_count", "size_bytes"}
    assert rows[0]["hits"] == 0


@pytest.mark.asyncio
async def test_snapshot_is_throttled(tmp_path):
    cache = EmbeddingCacheService(db_path=tmp_path / "embeddings.db")
    await cache.initialize(provider_fingerprint="t")
    assert await cache.maybe_snapshot(min_interval_s=3600.0) is True
    assert await cache.maybe_snapshot(min_interval_s=3600.0) is False
    rows = await cache.get_stats_history()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_history_since_filter(tmp_path):
    cache = EmbeddingCacheService(db_path=tmp_path / "embeddings.db")
    await cache.initialize(provider_fingerprint="t")
    await cache.maybe_snapshot(min_interval_s=0.0)
    await cache.maybe_snapshot(min_interval_s=0.0)
    rows = await cache.get_stats_history()
    assert len(rows) == 2
    later = await cache.get_stats_history(since=rows[-1]["ts"])
    assert len(later) >= 1
    assert all(r["ts"] >= rows[-1]["ts"] for r in later)


@pytest.mark.asyncio
async def test_snapshot_prunes_rows_older_than_retention(tmp_path):
    cache = EmbeddingCacheService(db_path=tmp_path / "embeddings.db")
    await cache.initialize(provider_fingerprint="t")

    old_ts = time.time() - 31 * 86400
    assert old_ts < time.time() - STATS_HISTORY_RETENTION_S
    async with aiosqlite.connect(cache.db_path) as db:
        await db.execute(
            "INSERT INTO stats_history "
            "(ts, hits, misses, entry_count, size_bytes) VALUES (?,?,?,?,?)",
            (old_ts, 1, 1, 1, 1),
        )
        await db.commit()

    assert await cache.maybe_snapshot(min_interval_s=0.0) is True
    rows = await cache.get_stats_history()
    assert len(rows) == 1
    assert rows[0]["ts"] > old_ts
