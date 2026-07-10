"""Task 9 — freeze MCP omission of include_sensitive.

The MCP front-end must NEVER reveal sensitive rows: query/recall/session_context
call the client without ``include_sensitive`` so the server's default-deny holds.
These tests freeze that policy against a future refactor — critical for recall
and session_context, which inject curated memory straight into AI context.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from brainpalace_cli.client.api_client import QueryResponse
from brainpalace_cli.mcp_server import tools as tools_mod
from brainpalace_cli.mcp_server.schemas import (
    QueryInput,
    RecallInput,
    SessionContextInput,
)

# --- Source-scan floor -----------------------------------------------------


def test_query_sync_never_sets_include_sensitive():
    src = inspect.getsource(tools_mod._query_sync)
    assert "include_sensitive" not in src  # MCP must never opt in


def test_recall_and_context_never_set_include_sensitive():
    # curated memory -> AI context: must default-deny by omission
    for fn in (tools_mod._recall_sync, tools_mod._session_context_sync):
        assert "include_sensitive" not in inspect.getsource(fn)


# --- Behavioral: the client is called WITHOUT include_sensitive ------------


class _CapturingClient:
    """Captures kwargs each client method is invoked with."""

    calls: dict[str, dict[str, Any]] = {}

    def __init__(self, *a: Any, **k: Any) -> None: ...

    def __enter__(self) -> _CapturingClient:
        return self

    def __exit__(self, *a: Any) -> None: ...

    def query(self, **kwargs: Any) -> Any:
        _CapturingClient.calls["query"] = kwargs
        return QueryResponse(results=[], total_results=0, query_time_ms=0.0)

    def recall(self, query: str, **kwargs: Any) -> dict[str, Any]:
        _CapturingClient.calls["recall"] = {"query": query, **kwargs}
        return {"hits": []}

    def session_context(self, **kwargs: Any) -> dict[str, Any]:
        _CapturingClient.calls["session_context"] = kwargs
        return {"text": ""}


@pytest.fixture
def capturing(monkeypatch):
    _CapturingClient.calls = {}
    monkeypatch.setattr(tools_mod, "DocServeClient", _CapturingClient)
    monkeypatch.setattr(tools_mod, "discover_server_url", lambda *_: "http://x")
    return _CapturingClient


def test_query_call_omits_include_sensitive(capturing):
    tools_mod._query_sync(QueryInput(query="x"))
    assert "include_sensitive" not in capturing.calls["query"]


def test_recall_call_omits_include_sensitive(capturing):
    tools_mod._recall_sync(RecallInput(query="x"))
    assert "include_sensitive" not in capturing.calls["recall"]


def test_session_context_call_omits_include_sensitive(capturing):
    tools_mod._session_context_sync(SessionContextInput())
    assert "include_sensitive" not in capturing.calls["session_context"]
