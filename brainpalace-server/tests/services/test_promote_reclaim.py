import json
from types import SimpleNamespace

import pytest

from brainpalace_server.services.memory_service import MemoryService
from brainpalace_server.services.session_linker import promote_decisions


def _payload(session_id, decisions):
    return SimpleNamespace(session_id=session_id, decisions=decisions)


def _dec(text, rationale="r", supersedes=None):
    return SimpleNamespace(text=text, rationale=rationale, supersedes=supersedes)


@pytest.mark.asyncio
async def test_promote_uses_reclaim_and_supersession(tmp_path):
    svc = MemoryService(path=tmp_path / "m.md", char_cap=8000)
    await promote_decisions(_payload("s1", [_dec("use Postgres")]), svc)
    await promote_decisions(
        _payload("s2", [_dec("use SQLite", supersedes="use Postgres")]), svc
    )
    active = [m.text for m in svc.load() if m.is_active]
    assert any("SQLite" in t for t in active)
    assert not any("Postgres" in t for t in active)


@pytest.mark.asyncio
async def test_cap_pressure_marker_written_not_silent(tmp_path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    svc = MemoryService(path=tmp_path / "m.md", char_cap=250)
    await svc.add("manual sacred fact padding padding", origin="user")
    n = await promote_decisions(
        _payload("s1", [_dec("overflow decision padding padding padding")]),
        svc,
        state_dir=state,
    )
    assert n == 0
    marker = state / "memory_cap_pressure.json"
    assert marker.exists()
    assert json.loads(marker.read_text())["skipped"] >= 1


@pytest.mark.asyncio
async def test_cap_pressure_marker_cleared_on_success(tmp_path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "memory_cap_pressure.json").write_text('{"at": "x", "skipped": 3}')
    svc = MemoryService(path=tmp_path / "m.md", char_cap=8000)
    await promote_decisions(
        _payload("s1", [_dec("plenty of room decision")]), svc, state_dir=state
    )
    # A successful promotion clears the stale warning.
    assert not (state / "memory_cap_pressure.json").exists()
