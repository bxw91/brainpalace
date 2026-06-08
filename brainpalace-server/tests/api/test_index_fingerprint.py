from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from brainpalace_server.api.routers import index as index_router


def _app_with_state(state: dict) -> FastAPI:
    app = FastAPI()
    app.include_router(index_router.router, prefix="/index")
    for k, v in state.items():
        setattr(app.state, k, v)
    return app


@pytest.mark.asyncio
async def test_fingerprint_reports_data_and_identity():
    vs = SimpleNamespace(
        get_embedding_metadata=AsyncMock(
            return_value={
                "provider": "openai",
                "model": "text-embedding-3-large",
                "dimensions": 3072,
            }
        )
    )
    app = _app_with_state(
        {
            "vector_store": vs,
            "storage_backend_name": "chroma",
            "graph_store_type": "sqlite",
        }
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/index/fingerprint")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_data"] is True
    assert body["embedding"] == {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "dimensions": 3072,
    }
    assert body["storage_backend"] == "chroma"
    assert body["graph_store_type"] == "sqlite"


@pytest.mark.asyncio
async def test_fingerprint_has_data_false_when_no_metadata():
    vs = SimpleNamespace(get_embedding_metadata=AsyncMock(return_value=None))
    app = _app_with_state({"vector_store": vs})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/index/fingerprint")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_data"] is False
    assert body["embedding"] is None
