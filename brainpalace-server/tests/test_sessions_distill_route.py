"""POST /sessions/distill route (Task 5)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from brainpalace_server.api.routers.sessions import DistillRequest, distill_sessions


class SpyDistiller:
    def __init__(self):
        self.scheduled: list = []

    def schedule(self, path, *, force=False):
        self.scheduled.append((path, force))


def _request(distiller):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(session_distiller=distiller))
    )


@pytest.mark.asyncio
async def test_503_when_distiller_absent():
    req = DistillRequest(paths=["a.jsonl"])
    with pytest.raises(HTTPException) as exc:
        await distill_sessions(req, _request(None))
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_enqueues_per_path():
    spy = SpyDistiller()
    req = DistillRequest(paths=["a.jsonl", "b.jsonl"])
    result = await distill_sessions(req, _request(spy))
    assert result["enqueued"] == 2
    assert [p for p, _ in spy.scheduled] == ["a.jsonl", "b.jsonl"]


@pytest.mark.asyncio
async def test_force_passthrough():
    spy = SpyDistiller()
    req = DistillRequest(paths=["a.jsonl"], force=True)
    result = await distill_sessions(req, _request(spy))
    assert result["force"] is True
    assert spy.scheduled[0][1] is True
