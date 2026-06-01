"""MCP server wiring for BrainPalace.

Registers the five read-only v1 tools with the official ``mcp`` SDK,
parses each call's arguments through the matching Pydantic schema, and
dispatches to the matching handler in :mod:`brainpalace_cli.mcp.tools`.
Transport is stdio — clients spawn ``brainpalace mcp`` as a child
process and speak MCP over the process's stdin/stdout.

``run_stdio(ensure_server=...)`` is the single entry point. The
optional flag hardens problem 1 (HTTP server not auto-started) from
the Phase Q plan: when set, the shim asks
:func:`brainpalace_cli.mcp.lifecycle.ensure_http_server` to start the
HTTP server for the spawn-time CWD project if discovery finds none.
The flag is wired from the CLI (``brainpalace mcp --ensure-server``)
and is OFF by default — Claude Code already has a start hook.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import BaseModel

from .schemas import (
    FoldersListInput,
    JobsListInput,
    MemorizeInput,
    QueryInput,
    RecallInput,
    SessionContextInput,
    StatusInput,
    WhoamiInput,
)
from .tools import (
    folders_list_tool,
    jobs_list_tool,
    memorize_tool,
    query_tool,
    recall_tool,
    session_context_tool,
    status_tool,
    whoami_tool,
)

app: Server = Server("brainpalace")

# Tool descriptions kept intentionally terse — every byte ships in every
# MCP client's context window (see the "tool description context cost"
# risk in the Phase Q plan).
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "query": (
        "Search indexed docs / code via BM25, vector, hybrid, graph, "
        "or multi-mode fusion."
    ),
    "status": "BrainPalace server health and indexing state.",
    "whoami": (
        "Resolve project root and server URL for the given path "
        "(or the MCP process CWD)."
    ),
    "folders_list": "List registered indexed folders.",
    "jobs_list": "List queued, running, and completed indexing jobs.",
    "memorize": "Save a durable curated fact to the project memory namespace.",
    "recall": "Recall curated facts from the project memory namespace only.",
    "session_context": ("Session-start context block: project facts + curated memory."),
}

# Maps tool name → (schema class, async handler). The schema parses and
# validates arguments before the handler ever sees them.
_DISPATCH: dict[str, tuple[type[BaseModel], Any]] = {
    "query": (QueryInput, query_tool),
    "status": (StatusInput, status_tool),
    "whoami": (WhoamiInput, whoami_tool),
    "folders_list": (FoldersListInput, folders_list_tool),
    "jobs_list": (JobsListInput, jobs_list_tool),
    "memorize": (MemorizeInput, memorize_tool),
    "recall": (RecallInput, recall_tool),
    "session_context": (SessionContextInput, session_context_tool),
}


@app.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
async def list_tools() -> list[types.Tool]:
    """Advertise the v1 tool surface to the connected MCP client."""
    return [
        types.Tool(
            name=name,
            description=_TOOL_DESCRIPTIONS[name],
            inputSchema=schema_cls.model_json_schema(),
        )
        for name, (schema_cls, _handler) in _DISPATCH.items()
    ]


@app.call_tool()  # type: ignore[untyped-decorator]
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Validate arguments, dispatch to the handler, return one TextContent block."""
    if name not in _DISPATCH:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": f"unknown tool: {name}"}),
            )
        ]
    schema_cls, handler = _DISPATCH[name]
    try:
        parsed = schema_cls(**(arguments or {}))
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError + anything else
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": f"invalid arguments for {name}: {exc}"}),
            )
        ]
    result = await handler(parsed)
    return [types.TextContent(type="text", text=json.dumps(result))]


def run_stdio(ensure_server: bool = False) -> None:
    """Serve MCP over stdio. Blocks until the client disconnects.

    If ``ensure_server`` is true, attempt to start the BrainPalace HTTP
    server for the spawn-time CWD project before opening the stdio
    loop — see Task 5.5 in the Phase Q plan.
    """
    if ensure_server:
        # Lazy import: keeps the dependency optional and lets server.py
        # be imported in tests before lifecycle.py exists.
        from .lifecycle import ensure_http_server

        ensure_http_server()

    async def _main() -> None:
        async with stdio_server() as (read, write):
            await app.run(read, write, app.create_initialization_options())

    asyncio.run(_main())
