"""Task 9 — freeze dashboard /replay omission of include_sensitive.

The dashboard is a shared surface that must never reveal sensitive rows. Its
replay proxy copies only a fixed payload whitelist (query/mode/top_k + optional
alpha/rerank) from the request body, so ``include_sensitive`` in the body is
dropped. This test freezes that policy against a future refactor.
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi.testclient import TestClient

import brainpalace_dashboard.api.routes_queries as rq
from brainpalace_dashboard.app import create_app


class _FakeProxy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any, Any]] = []

    async def request(self, id_, method, path, json=None, params=None):
        self.calls.append((method, path, json, params))
        return {"results": [], "query_time_ms": 1.0}


def test_replay_drops_include_sensitive_from_body(monkeypatch):
    fake = _FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    c.post(
        "/dashboard/api/instances/abc/queries/replay",
        json={"query": "x", "mode": "hybrid", "top_k": 5, "include_sensitive": True},
    )
    _method, _path, body, _params = fake.calls[-1]
    assert "include_sensitive" not in body  # never proxied upstream


def test_replay_payload_whitelist_excludes_sensitive():
    src = inspect.getsource(rq.replay)
    assert "include_sensitive" not in src  # shared surface; never reveal
