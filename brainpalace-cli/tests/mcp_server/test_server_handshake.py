"""Integration tests for ``brainpalace_cli.mcp.server``.

Exercises the ``list_tools``/``call_tool`` async surface directly —
the SDK's stdio transport is not started, since the goal is to verify
this module's dispatch + schema parsing + JSON-content packaging, not
the MCP SDK itself.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import BaseModel

from brainpalace_cli.mcp_server import server


def test_list_tools_returns_expected_tools() -> None:
    tools = asyncio.run(server.list_tools())

    names = [t.name for t in tools]
    assert names == [
        "query",
        "status",
        "whoami",
        "folders_list",
        "jobs_list",
        "memorize",
        "recall",
        "session_context",
        "ai_guide",
        "extraction_fetch",
        "extraction_submit",
    ]


def test_list_tools_schemas_carry_path_arg() -> None:
    """The CWD-coupling hardening — every non-whoami tool exposes a ``path`` field."""
    tools = {t.name: t for t in asyncio.run(server.list_tools())}

    for name in ("query", "status", "folders_list", "jobs_list"):
        props = tools[name].inputSchema.get("properties", {})
        assert "path" in props, f"{name} schema missing path arg"

    # whoami keeps its older ``file_path`` name.
    assert "file_path" in tools["whoami"].inputSchema.get("properties", {})


def test_list_tools_descriptions_terse() -> None:
    """Risk register budget: total descriptions ≤ 730 chars (11 tools).

    Raised from 575 when the two extraction tools (``extraction_fetch`` /
    ``extraction_submit``) were added for the unified auto-drain; descriptions
    stay one-line terse — doctrine lives in the server ``instructions=`` (CORE
    tier), not duplicated into per-tool descriptions.
    """
    tools = asyncio.run(server.list_tools())
    total = sum(len(t.description or "") for t in tools)
    assert total <= 730, f"description budget exceeded: {total} chars"


def test_call_tool_unknown_name_returns_error() -> None:
    result = asyncio.run(server.call_tool("does_not_exist", {}))

    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload == {"error": "unknown tool: does_not_exist"}


def test_call_tool_invalid_arguments_returns_validation_error() -> None:
    # mode='bogus' is not one of the Literal values in QueryInput.
    result = asyncio.run(server.call_tool("query", {"query": "x", "mode": "bogus"}))

    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "invalid arguments for query" in payload["error"]


def test_call_tool_dispatches_and_serialises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace one dispatch entry; verify args are parsed and result is JSON-packed."""
    seen: dict[str, Any] = {}

    class _Schema(BaseModel):
        path: str | None = None

    async def _handler(parsed: _Schema) -> dict[str, Any]:
        seen["parsed"] = parsed
        return {"ok": True, "echoed_path": parsed.path}

    monkeypatch.setitem(server._DISPATCH, "status", (_Schema, _handler))

    result = asyncio.run(server.call_tool("status", {"path": "/p/demo"}))

    assert isinstance(seen["parsed"], _Schema)
    assert seen["parsed"].path == "/p/demo"

    payload = json.loads(result[0].text)
    assert payload == {"ok": True, "echoed_path": "/p/demo"}


def test_call_tool_handles_none_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Some MCP clients send no arguments — ``call_tool`` must accept ``None``
    and dispatch with a default-constructed schema (``None`` -> ``{}``).

    Mocks the dispatch entry so the assertion does not depend on whether a real
    BrainPalace server happens to be running in the test environment.
    """
    seen: dict[str, Any] = {}

    class _Schema(BaseModel):
        path: str | None = None

    async def _handler(parsed: _Schema) -> dict[str, Any]:
        seen["parsed"] = parsed
        return {"ok": True, "path": parsed.path}

    monkeypatch.setitem(server._DISPATCH, "status", (_Schema, _handler))

    result = asyncio.run(server.call_tool("status", None))

    assert isinstance(seen["parsed"], _Schema)
    assert seen["parsed"].path is None  # None args -> {} -> schema defaults
    payload = json.loads(result[0].text)
    assert payload == {"ok": True, "path": None}
