"""Task 7 — /query forwards include_sensitive to execute_query unchanged.

Guards against a future field strip: the router passes the whole
QueryRequest through, so this proves the flag survives the round trip rather
than asserting anything new (the pass-through already works).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.query import router as query_router
from brainpalace_server.models.query import QueryRequest, QueryResponse


class _FakeQueryService:
    def __init__(self) -> None:
        self.captured: dict[str, object] = {}
        self.execute_query = AsyncMock(side_effect=self._execute)

    async def _execute(self, req: QueryRequest) -> QueryResponse:
        self.captured["flag"] = req.include_sensitive
        return QueryResponse(results=[], total_results=0, query_time_ms=0.0)

    def is_ready(self) -> bool:
        return True


class _FakeIndexingService:
    is_indexing = False


def _client() -> tuple[TestClient, _FakeQueryService]:
    app = FastAPI()
    app.include_router(query_router, prefix="/query")
    query_service = _FakeQueryService()
    app.state.query_service = query_service
    app.state.indexing_service = _FakeIndexingService()
    return TestClient(app), query_service


def test_router_forwards_include_sensitive_true():
    client, query_service = _client()
    resp = client.post("/query/", json={"query": "x", "include_sensitive": True})
    assert resp.status_code == 200
    assert query_service.captured["flag"] is True


def test_router_forwards_include_sensitive_default_false():
    client, query_service = _client()
    resp = client.post("/query/", json={"query": "x"})
    assert resp.status_code == 200
    assert query_service.captured["flag"] is False
