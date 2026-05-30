"""LspClient JSON-RPC framing + request/response (Phase 150).

Stream-backed so no real language server is needed: a ``BytesIO`` feeds canned
responses and captures what the client writes.
"""

from __future__ import annotations

import io
import json

from brainpalace_server.lsp.client import LspClient, frame_message, read_message


def _framed(obj: dict) -> bytes:
    return frame_message(obj)


class TestFraming:
    def test_frame_has_content_length_header(self) -> None:
        raw = frame_message({"jsonrpc": "2.0", "id": 1, "method": "x"})
        head, _, body = raw.partition(b"\r\n\r\n")
        assert head == b"Content-Length: %d" % len(body)
        assert json.loads(body)["method"] == "x"

    def test_read_message_roundtrip(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}
        stream = io.BytesIO(frame_message(msg))
        assert read_message(stream) == msg

    def test_read_message_eof_returns_none(self) -> None:
        assert read_message(io.BytesIO(b"")) is None


class TestRequest:
    def test_request_writes_and_matches_id(self) -> None:
        writer = io.BytesIO()
        # canned response for the first request (id starts at 1)
        reader = io.BytesIO(
            frame_message({"jsonrpc": "2.0", "id": 1, "result": [{"hit": 1}]})
        )
        client = LspClient(reader=reader, writer=writer)
        result = client.request("textDocument/references", {"x": 1})
        assert result == [{"hit": 1}]
        # what we sent:
        sent = read_message(io.BytesIO(writer.getvalue()))
        assert sent["method"] == "textDocument/references"
        assert sent["id"] == 1
        assert sent["params"] == {"x": 1}

    def test_request_skips_notifications_until_match(self) -> None:
        writer = io.BytesIO()
        reader = io.BytesIO(
            frame_message({"jsonrpc": "2.0", "method": "window/logMessage",
                           "params": {"m": "noise"}})
            + frame_message({"jsonrpc": "2.0", "id": 1, "result": "ok"})
        )
        client = LspClient(reader=reader, writer=writer)
        assert client.request("any", {}) == "ok"

    def test_request_raises_on_error_response(self) -> None:
        writer = io.BytesIO()
        reader = io.BytesIO(
            frame_message({"jsonrpc": "2.0", "id": 1,
                           "error": {"code": -32601, "message": "no"}})
        )
        client = LspClient(reader=reader, writer=writer)
        try:
            client.request("bad", {})
            raised = False
        except Exception:
            raised = True
        assert raised

    def test_notify_has_no_id(self) -> None:
        writer = io.BytesIO()
        client = LspClient(reader=io.BytesIO(), writer=writer)
        client.notify("initialized", {})
        sent = read_message(io.BytesIO(writer.getvalue()))
        assert "id" not in sent
        assert sent["method"] == "initialized"
