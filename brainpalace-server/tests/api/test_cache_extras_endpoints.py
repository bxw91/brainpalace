"""Cache history + economics endpoints (dashboard plan 04)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import cache as cache_router_mod
from brainpalace_server.services.embedding_cache import (
    EmbeddingCacheService,
    get_embedding_cache,
    reset_embedding_cache,
    set_embedding_cache,
)


@pytest.fixture
def app_with_cache(tmp_path):
    cache = EmbeddingCacheService(db_path=tmp_path / "embeddings.db")

    import asyncio

    asyncio.run(cache.initialize(provider_fingerprint="t"))
    set_embedding_cache(cache)
    sub = FastAPI()
    sub.include_router(cache_router_mod.router, prefix="/index/cache")
    yield sub
    reset_embedding_cache()


def test_history_returns_snapshots(app_with_cache):
    c = TestClient(app_with_cache)
    r = c.get("/index/cache/history")
    assert r.status_code == 200
    # First read triggers the opportunistic snapshot.
    assert len(r.json()["snapshots"]) == 1


def test_economics_known_provider(app_with_cache):
    fake_settings = MagicMock()
    fake_settings.embedding.provider = "openai"
    fake_settings.embedding.model = "text-embedding-3-small"
    with patch.object(
        cache_router_mod, "load_provider_settings", return_value=fake_settings
    ):
        c = TestClient(app_with_cache)
        r = c.get("/index/cache/economics?avg_tokens=1000")
    assert r.status_code == 200
    body = r.json()
    assert body["price_usd_per_mtok"] == 0.02
    assert body["session_hits"] == 0
    assert body["est_saved_usd"] == 0.0


def test_economics_unknown_provider_has_null_estimates(app_with_cache):
    fake_settings = MagicMock()
    fake_settings.embedding.provider = "ollama"
    fake_settings.embedding.model = "nomic-embed-text"
    with patch.object(
        cache_router_mod, "load_provider_settings", return_value=fake_settings
    ):
        c = TestClient(app_with_cache)
        r = c.get("/index/cache/economics")
    body = r.json()
    assert body["price_usd_per_mtok"] is None
    assert body["est_saved_usd"] is None


def test_economics_computes_costs_from_counters(app_with_cache):
    cache = get_embedding_cache()
    cache._hits = 5000
    cache._misses = 1000
    fake_settings = MagicMock()
    fake_settings.embedding.provider = "openai"
    fake_settings.embedding.model = "text-embedding-3-small"
    with patch.object(
        cache_router_mod, "load_provider_settings", return_value=fake_settings
    ):
        c = TestClient(app_with_cache)
        r = c.get("/index/cache/economics?avg_tokens=400")
    body = r.json()
    assert body["avg_tokens_per_chunk"] == 400
    # misses * 400 / 1e6 * 0.02
    assert body["est_spend_usd"] == pytest.approx(0.008)
    assert body["est_saved_usd"] == pytest.approx(0.04)


def test_economics_rejects_invalid_avg_tokens(app_with_cache):
    c = TestClient(app_with_cache)
    assert c.get("/index/cache/economics?avg_tokens=0").status_code == 422
    assert c.get("/index/cache/history?since=-1").status_code == 422


def test_history_503_without_cache():
    reset_embedding_cache()
    sub = FastAPI()
    sub.include_router(cache_router_mod.router, prefix="/index/cache")
    c = TestClient(sub)
    assert c.get("/index/cache/history").status_code == 503
    assert c.get("/index/cache/economics").status_code == 503
