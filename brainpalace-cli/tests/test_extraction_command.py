"""Tests for `brainpalace extraction pending|submit` CLI (Plan 3, Task 3).

Also covers the Task 5 client method ``get_extraction_text``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from brainpalace_cli.client.api_client import DocServeClient


def test_get_extraction_pending_calls_endpoint():
    client = DocServeClient(base_url="http://x")
    client._request = MagicMock(return_value={"items": [], "doc_pending_total": 0})
    out = client.get_extraction_pending(15)
    client._request.assert_called_once()
    args, kwargs = client._request.call_args
    assert (
        args[0] == "GET" and "/extraction/pending" in args[1] and "limit=15" in args[1]
    )
    assert out["doc_pending_total"] == 0


def test_get_extraction_pending_passes_source():
    client = DocServeClient(base_url="http://x")
    client._request = MagicMock(return_value={"items": [], "doc_pending_total": 0})
    client.get_extraction_pending(10, source="doc")
    args, _kwargs = client._request.call_args
    assert "source=doc" in args[1] and "limit=10" in args[1]


def test_get_extraction_pending_defaults_source_all():
    client = DocServeClient(base_url="http://x")
    client._request = MagicMock(return_value={"items": [], "doc_pending_total": 0})
    client.get_extraction_pending(5)
    args, _kwargs = client._request.call_args
    assert "source=all" in args[1]


def test_pending_command_forwards_source(monkeypatch):
    from click.testing import CliRunner

    import brainpalace_cli.commands.extraction as ext

    captured = {}

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_extraction_pending(self, limit, source="all"):
            captured["limit"] = limit
            captured["source"] = source
            return {"items": [], "doc_pending_total": 0}

    monkeypatch.setattr(ext, "DocServeClient", lambda *a, **k: _FakeClient())
    monkeypatch.setattr(ext, "get_server_url", lambda: "http://x")
    res = CliRunner().invoke(ext.pending_command, ["--limit", "7", "--source", "doc"])
    assert res.exit_code == 0, res.output
    assert captured == {"limit": 7, "source": "doc"}


def test_submit_extraction_posts_payload():
    client = DocServeClient(base_url="http://x")
    client._request = MagicMock(return_value={"source": "doc", "id": "c1"})
    client.submit_extraction({"source": "doc", "chunk_id": "c1", "triplets": []})
    args, kwargs = client._request.call_args
    assert args[0] == "POST" and args[1] == "/extraction/submit"
    assert kwargs["json"]["chunk_id"] == "c1"


# ---------------------------------------------------------------------------
# Task 5: get_extraction_text
# ---------------------------------------------------------------------------


def test_get_extraction_text_calls_endpoint():
    c = DocServeClient(base_url="http://x")
    c._request = MagicMock(return_value={"chunk_id": "c1", "text": "t"})
    c.get_extraction_text("c1")
    args, _ = c._request.call_args
    assert args[0] == "GET" and args[1] == "/extraction/text/c1"


# ---------------------------------------------------------------------------
# Task 10: `brainpalace extraction text <chunk_id>`
# ---------------------------------------------------------------------------


def test_text_command_fetches_and_echoes_json(monkeypatch):
    import json

    from click.testing import CliRunner

    import brainpalace_cli.commands.extraction as ext

    captured = {}

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_extraction_text(self, chunk_id):
            captured["chunk_id"] = chunk_id
            return {"chunk_id": chunk_id, "text": "alpha beta"}

    monkeypatch.setattr(ext, "DocServeClient", lambda *a, **k: _FakeClient())
    monkeypatch.setattr(ext, "get_server_url", lambda: "http://x")
    res = CliRunner().invoke(ext.text_command, ["c1"])
    assert res.exit_code == 0, res.output
    assert captured == {"chunk_id": "c1"}
    assert json.loads(res.output) == {"chunk_id": "c1", "text": "alpha beta"}
