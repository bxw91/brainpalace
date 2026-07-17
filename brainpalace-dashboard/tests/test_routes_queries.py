from fastapi.testclient import TestClient

import brainpalace_dashboard.api.routes_queries as rq
from brainpalace_dashboard.app import create_app


class FakeProxy:
    def __init__(self):
        self.calls = []

    async def request(self, id_, method, path, json=None, params=None):
        self.calls.append((method, path, json, params))
        if path == "/query/history":
            return [{"id": "1", "query": "x"}]
        if path == "/query/history/1":
            return {"id": "1", "results": [{"path": "a.py"}]}
        if path == "/query/":
            return {"results": [{"path": "a.py"}], "query_time_ms": 1.0}
        if path == "/query/stats":
            return {"total": 3}
        return {}


def test_history_list(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    r = c.get("/dashboard/api/instances/abc/queries")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "1"


def test_history_list_passes_filters(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    c.get("/dashboard/api/instances/abc/queries?mode=bm25&contains=foo&limit=5")
    method, path, _json, params = fake.calls[-1]
    assert path == "/query/history"
    assert params["mode"] == "bm25"
    assert params["contains"] == "foo"
    assert params["limit"] == 5


def test_detail(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    r = c.get("/dashboard/api/instances/abc/queries/1")
    assert r.json()["results"][0]["path"] == "a.py"


def test_replay(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    r = c.post(
        "/dashboard/api/instances/abc/queries/replay",
        json={"query": "x", "mode": "hybrid", "top_k": 5},
    )
    assert r.json()["results"][0]["path"] == "a.py"
    method, path, body, _params = fake.calls[-1]
    assert method == "POST"
    assert path == "/query/"
    assert body == {"query": "x", "mode": "hybrid", "top_k": 5}


def test_replay_includes_alpha(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    c.post(
        "/dashboard/api/instances/abc/queries/replay",
        json={"query": "x", "alpha": 0.2},
    )
    _method, _path, body, _params = fake.calls[-1]
    assert body["alpha"] == 0.2
    assert body["mode"] == "hybrid"
    assert body["top_k"] == 5


def test_replay_forwards_rerank(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    c.post(
        "/dashboard/api/instances/abc/queries/replay",
        json={"query": "x", "mode": "hybrid", "top_k": 5, "rerank": False},
    )
    _method, path, body, _params = fake.calls[-1]
    assert path == "/query/"
    assert body["rerank"] is False


def test_replay_omits_rerank_when_absent(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    c.post(
        "/dashboard/api/instances/abc/queries/replay",
        json={"query": "x", "mode": "hybrid", "top_k": 5},
    )
    _method, _path, body, _params = fake.calls[-1]
    assert "rerank" not in body


def test_replay_forwards_logged_scope_filters(monkeypatch):
    """A18 — a replay must carry the logged scope filters, or it silently
    re-runs a broader query than the one being replayed."""
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    c.post(
        "/dashboard/api/instances/abc/queries/replay",
        json={
            "query": "x",
            "mode": "bm25",
            "top_k": 5,
            "filters": {
                "source_types": ["code"],
                "languages": ["python"],
                "file_paths": ["*dashboard*"],
                "domains": [],  # empty -> not forwarded
            },
        },
    )
    _method, _path, body, _params = fake.calls[-1]
    assert body["source_types"] == ["code"]
    assert body["languages"] == ["python"]
    assert body["file_paths"] == ["*dashboard*"]
    assert "domains" not in body  # empty filters are not forwarded


def test_replay_never_forwards_nested_include_sensitive(monkeypatch):
    """The scope-filter allowlist must not let a crafted body smuggle the
    sensitivity gate back in through the nested `filters` object."""
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    c.post(
        "/dashboard/api/instances/abc/queries/replay",
        json={
            "query": "x",
            "mode": "hybrid",
            "top_k": 5,
            "filters": {"source_types": ["code"], "include_sensitive": True},
        },
    )
    _method, _path, body, _params = fake.calls[-1]
    assert body["source_types"] == ["code"]
    assert "include_sensitive" not in body


def test_stats_proxies_with_params(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    r = c.get("/dashboard/api/instances/abc/queries/stats?since=9.5&top_n=3")
    assert r.status_code == 200
    assert r.json()["total"] == 3
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/query/stats")
    assert params == {"since": 9.5, "top_n": 3}


def test_stats_not_shadowed_by_detail_route(monkeypatch):
    """'/stats' must never be captured by the '/{qid}' detail route."""
    fake = FakeProxy()
    monkeypatch.setattr(rq, "proxy", fake)
    c = TestClient(create_app())
    c.get("/dashboard/api/instances/abc/queries/stats")
    _method, path, _json, _params = fake.calls[-1]
    assert path == "/query/stats"  # NOT /query/history/stats
