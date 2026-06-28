"""Task-3 Step-5: embedding generator and queue-sample instrumentation tests."""

import pytest

import brainpalace_server.services.usage_metrics as um
from brainpalace_server.providers.base import Usage
from brainpalace_server.storage.usage_metrics_store import (
    UsageMetricsStore,
)


@pytest.mark.asyncio
async def test_embedding_records_with_contextvar_source(tmp_path, monkeypatch):
    store = UsageMetricsStore(tmp_path / "u.db")
    um.set_usage_store(store)
    try:
        from brainpalace_server.indexing import embedding as eg
        from brainpalace_server.indexing.embedding import reset_embedding_generator

        # Reset singleton so we get a fresh instance for the test
        reset_embedding_generator()
        gen = eg.get_embedding_generator()

        # fake the provider's usage-returning path
        # Real attribute is gen._embedding_provider (not gen._provider)
        async def fake(texts, progress_callback=None):
            return [[0.0]] * len(texts), Usage(tokens_in=42)

        monkeypatch.setattr(
            gen._embedding_provider, "embed_texts_with_usage", fake, raising=False
        )
        with um.usage_scope("doc"):
            await gen.embed_texts(["a", "b"])  # the instrumented wrapper
        totals, _ = store.aggregate(since_bucket=0)
        emb = next(t for t in totals if t["channel"] == "embedding")
        assert emb["source"] == "doc" and emb["chunks"] == 2 and emb["tokens_in"] == 42
    finally:
        um.set_usage_store(None)


@pytest.mark.asyncio
async def test_embedding_meters_only_cache_misses(tmp_path, monkeypatch):
    """With an embedding cache enabled, only the miss texts hit the provider
    and get metered; local-cache hits record no provider work (§6-F8)."""
    store = UsageMetricsStore(tmp_path / "u.db")
    um.set_usage_store(store)
    try:
        from brainpalace_server.indexing import embedding as eg
        from brainpalace_server.indexing.embedding import (
            reset_embedding_generator,
        )

        reset_embedding_generator()
        gen = eg.get_embedding_generator()

        # Fake an embedding cache: "a" is a hit, everything else is a miss.
        class _FakeCache:
            @staticmethod
            def make_cache_key(text, provider, model, dims):
                return text

            async def get_batch(self, keys):
                return {"a": [1.0]}  # only "a" cached

            async def put_many(self, items):
                return None

        fake_cache = _FakeCache()
        monkeypatch.setattr(
            "brainpalace_server.services.embedding_cache.get_embedding_cache",
            lambda: fake_cache,
        )
        monkeypatch.setattr(
            "brainpalace_server.services.embedding_cache."
            "EmbeddingCacheService.make_cache_key",
            _FakeCache.make_cache_key,
        )

        async def fake(texts, progress_callback=None):
            return [[0.0]] * len(texts), Usage(tokens_in=21, cache_read=3)

        monkeypatch.setattr(
            gen._embedding_provider,
            "embed_texts_with_usage",
            fake,
            raising=False,
        )
        with um.usage_scope("doc"):
            await gen.embed_texts(["a", "b", "c"])  # 1 hit, 2 misses

        totals, _ = store.aggregate(since_bucket=0)
        emb = next(t for t in totals if t["channel"] == "embedding")
        # Only the 2 misses are metered, not all 3 texts.
        assert emb["source"] == "doc"
        assert emb["chunks"] == 2 and emb["calls"] == 1
        assert emb["tokens_in"] == 21 and emb["cache_read"] == 3
    finally:
        um.set_usage_store(None)
        from brainpalace_server.indexing.embedding import (
            reset_embedding_generator,
        )

        reset_embedding_generator()


def test_queue_sample_records_depth(tmp_path):
    store = UsageMetricsStore(tmp_path / "u.db")
    um.set_usage_store(store)
    try:
        um.sample_queue("session", 698)
        assert {r["source"]: r["depth"] for r in store.queue_latest()}["session"] == 698
    finally:
        um.set_usage_store(None)
