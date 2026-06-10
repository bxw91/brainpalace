"""Live provider connectivity test endpoint (dashboard plan 07).

Embedding: one real embed_query("ping") round-trip (costs ~1 token — only
runs on explicit user click). Summarization: config-level validation only,
no LLM spend.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import health as health_mod


def _app():
    sub = FastAPI()
    sub.include_router(health_mod.router, prefix="/health")
    return sub


def _provider_settings():
    s = MagicMock()
    s.embedding.provider = "openai"
    s.embedding.model = "text-embedding-3-small"
    s.summarization.provider = "anthropic"
    s.summarization.model = "claude-haiku-4-5-20251001"
    return s


def test_providers_test_ok():
    embedder = MagicMock()
    embedder.embed_query = AsyncMock(return_value=[0.1] * 8)
    with (
        patch.object(health_mod, "get_embedding_generator", return_value=embedder),
        patch.object(
            health_mod, "load_provider_settings", return_value=_provider_settings()
        ),
    ):
        c = TestClient(_app())
        r = c.post("/health/providers/test")
    assert r.status_code == 200
    body = r.json()
    assert body["embedding"]["ok"] is True
    assert body["embedding"]["model"] == "text-embedding-3-small"
    assert body["embedding"]["latency_ms"] >= 0
    assert body["summarization"]["checked"] == "config-only"


def test_providers_test_embedding_failure_reported_not_raised():
    embedder = MagicMock()
    embedder.embed_query = AsyncMock(side_effect=RuntimeError("401 bad key"))
    with (
        patch.object(health_mod, "get_embedding_generator", return_value=embedder),
        patch.object(
            health_mod, "load_provider_settings", return_value=_provider_settings()
        ),
    ):
        c = TestClient(_app())
        r = c.post("/health/providers/test")
    assert r.status_code == 200
    body = r.json()
    assert body["embedding"]["ok"] is False
    assert "401" in body["embedding"]["error"]
