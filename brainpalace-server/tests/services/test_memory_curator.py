import json

import pytest

from brainpalace_server.services.memory_curator_service import MemoryCurator
from brainpalace_server.services.memory_service import MemoryService


class _Summ:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        return self.reply


@pytest.mark.asyncio
async def test_curator_deletes_and_obsoletes_from_ops(tmp_path):
    svc = MemoryService(path=tmp_path / "m.md")
    a = await svc.add("dup fact one", origin="session:s1")
    b = await svc.add("stale fact two", origin="session:s2")
    keep = await svc.add("keep this fact", origin="user")
    reply = json.dumps({"delete": [a.id], "obsolete": [{"id": b.id}]})
    state = tmp_path / ".brainpalace"
    state.mkdir()
    n = await MemoryCurator(_Summ(reply), svc).curate_if_due(state)
    assert n == 2
    active = {m.id for m in svc.load() if m.is_active}
    assert a.id not in active  # deleted (physically gone)
    assert b.id not in active  # obsoleted (inactive)
    assert keep.id in active
    assert (state / "state" / "last-curate").exists()  # stamped on completed run


@pytest.mark.asyncio
async def test_curator_no_stamp_and_no_change_on_bad_json(tmp_path):
    svc = MemoryService(path=tmp_path / "m.md")
    await svc.add("fact", origin="session:s1")
    state = tmp_path / ".brainpalace"
    state.mkdir()
    n = await MemoryCurator(_Summ("not json at all"), svc).curate_if_due(state)
    assert n == 0
    assert not (state / "state" / "last-curate").exists()  # failed parse → retry later
    assert len([m for m in svc.load() if m.is_active]) == 1


@pytest.mark.asyncio
async def test_curator_skips_when_stamp_fresh(tmp_path, monkeypatch):
    svc = MemoryService(path=tmp_path / "m.md")
    await svc.add("fact", origin="session:s1")
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "state").mkdir()
    (state / "state" / "last-curate").touch()  # fresh
    summ = _Summ(json.dumps({"delete": []}))
    n = await MemoryCurator(summ, svc).curate_if_due(state)
    assert n == 0
    assert summ.calls == 0  # provider never called when not due


@pytest.mark.asyncio
async def test_curator_noop_when_memory_empty(tmp_path):
    svc = MemoryService(path=tmp_path / "m.md")
    state = tmp_path / ".brainpalace"
    state.mkdir()
    summ = _Summ(json.dumps({"delete": []}))
    n = await MemoryCurator(summ, svc).curate_if_due(state)
    assert n == 0
    assert summ.calls == 0
