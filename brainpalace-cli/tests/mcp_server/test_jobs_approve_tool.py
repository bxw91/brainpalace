"""jobs_approve MCP tool: registry entry + handler dispatch."""

from typing import Any

import pytest

from brainpalace_cli.mcp_server import server as server_mod
from brainpalace_cli.mcp_server import tools as tools_mod
from brainpalace_cli.mcp_server.schemas import JobsApproveInput


def test_tool_registered() -> None:
    assert "jobs_approve" in server_mod._DISPATCH


@pytest.mark.asyncio
async def test_jobs_approve_tool_calls_client(monkeypatch) -> None:
    class _FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *a: Any) -> None: ...
        def approve_job(self, job_id: str) -> dict[str, Any]:
            return {"job_id": job_id, "status": "pending", "message": "ok"}

    monkeypatch.setattr(tools_mod, "DocServeClient", _FakeClient)
    monkeypatch.setattr(tools_mod, "discover_server_url", lambda *_: "http://x")
    out = await tools_mod.jobs_approve_tool(JobsApproveInput(job_id="job_1"))
    assert out == {"job_id": "job_1", "status": "pending", "message": "ok"}


@pytest.mark.asyncio
async def test_jobs_approve_tool_server_down(monkeypatch) -> None:
    monkeypatch.setattr(tools_mod, "discover_server_url", lambda *_: None)
    out = await tools_mod.jobs_approve_tool(JobsApproveInput(job_id="job_1"))
    assert "error" in out


def test_blocked_suffix_from_jobs_list(monkeypatch) -> None:
    class _FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *a: Any) -> None: ...
        def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
            return [{"id": "job_blk", "status": "blocked"}]

    monkeypatch.setattr("brainpalace_cli.client.DocServeClient", _FakeClient)
    monkeypatch.setattr(server_mod, "discover_server_url", lambda *_: "http://x")
    suffix = server_mod._blocked_instructions_suffix()
    assert "job_blk" in suffix and "paused" in suffix


def test_blocked_suffix_empty_when_no_server(monkeypatch) -> None:
    monkeypatch.setattr(server_mod, "discover_server_url", lambda *_: None)
    assert server_mod._blocked_instructions_suffix() == ""
