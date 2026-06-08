import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import brainpalace_server.self_heal as sh


class _Req:
    def __init__(self, app, host_header):
        self.app = app
        self.scope = {"server": ("127.0.0.1", 8000), "scheme": "http"}
        self.headers = {"host": host_header}


@pytest.mark.asyncio
async def test_middleware_registers_once_off_path(monkeypatch):
    calls = []
    monkeypatch.setattr(sh, "register", lambda *a, **k: calls.append(k["base_url"]))

    app = SimpleNamespace(
        state=SimpleNamespace(
            state_dir=Path("/p/.brainpalace"),
            project_root="/p",
            registered_base_url=None,
        )
    )
    mw = sh.registration_middleware(app)

    async def call_next(_req):
        return "response"

    resp = await mw(_Req(app, "evil:9"), call_next)
    await asyncio.sleep(0)  # let the scheduled task run
    assert resp == "response"
    assert calls == ["http://127.0.0.1:8000"]  # scope host, not "evil"

    # second request: cached, no re-register
    await mw(_Req(app, "evil:9"), call_next)
    await asyncio.sleep(0)
    assert calls == ["http://127.0.0.1:8000"]
