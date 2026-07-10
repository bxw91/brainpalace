"""Task 8 — DocServeClient.query omits include_sensitive unless explicitly True."""

from __future__ import annotations

from brainpalace_cli.client.api_client import DocServeClient


def _capture_request_data(monkeypatch):
    captured: dict[str, object] = {}
    client = DocServeClient(base_url="http://x")

    def fake_request(method, path, json=None, params=None):
        captured.update(json or {})
        return {"results": [], "total_results": 0, "query_time_ms": 0.0}

    monkeypatch.setattr(client, "_request", fake_request)
    return client, captured


def test_query_omits_flag_by_default(monkeypatch):
    client, captured = _capture_request_data(monkeypatch)
    client.query(query_text="x")
    assert "include_sensitive" not in captured


def test_query_sends_flag_when_true(monkeypatch):
    client, captured = _capture_request_data(monkeypatch)
    client.query(query_text="x", include_sensitive=True)
    assert captured["include_sensitive"] is True
