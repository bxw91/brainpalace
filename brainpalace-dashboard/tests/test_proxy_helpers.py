import pytest

from brainpalace_dashboard.services.proxy import ProxyService, UpstreamError


@pytest.mark.asyncio
async def test_fetch_fingerprint_returns_none_when_server_down(monkeypatch):
    svc = ProxyService()

    async def boom(*a, **k):
        raise UpstreamError("down", 502)

    monkeypatch.setattr(svc, "request", boom)
    assert await svc.fetch_fingerprint("id1") is None


@pytest.mark.asyncio
async def test_fetch_fingerprint_passes_through(monkeypatch):
    svc = ProxyService()

    async def ok(id_, method, path, **k):
        assert (method, path) == ("GET", "/index/fingerprint")
        return {"has_data": True, "doc_count": 5}

    monkeypatch.setattr(svc, "request", ok)
    fp = await svc.fetch_fingerprint("id1")
    assert fp["has_data"] is True


@pytest.mark.asyncio
async def test_trigger_full_reindex_forces_each_folder(monkeypatch):
    svc = ProxyService()
    calls = []

    async def fake(id_, method, path, json=None, params=None):
        calls.append((method, path, json, params))
        if path == "/index/folders/":
            return {
                "folders": [{"folder_path": "/p/a"}, {"folder_path": "/p/b"}],
                "total": 2,
            }
        return {"job_id": "j"}

    monkeypatch.setattr(svc, "request", fake)
    count = await svc.trigger_full_reindex("id1")
    assert count == 2
    posts = [c for c in calls if c[0] == "POST"]
    assert all(c[1] == "/index/" for c in posts)
    assert all(c[3] == {"force": True} for c in posts)
    assert {c[2]["folder_path"] for c in posts} == {"/p/a", "/p/b"}
