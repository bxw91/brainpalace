# tests/rehome/test_orchestrator_copy_registry.py
"""Copy vs move: A15 must NOT de-register the original when old_root still exists
on disk (a COPY). It removes the old registry entry only for a genuine move."""

import pytest

from brainpalace_server.rehome import orchestrator as orch
from brainpalace_server.rehome.identity import ProjectIdentity, write_identity
from brainpalace_server.rehome.state import new_rehome_state, write_rehome_state


def _seed_pending_move(state_dir, old_root, new_root):
    write_identity(state_dir, ProjectIdentity("u", str(old_root)))
    st = new_rehome_state("u", str(old_root), str(new_root))
    write_rehome_state(state_dir, st)


@pytest.mark.asyncio
async def test_move_removes_old_registry_entry(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    old_root = tmp_path / "gone"  # does NOT exist on disk => a move
    new_root = tmp_path / "new"
    new_root.mkdir()
    _seed_pending_move(state_dir, old_root, new_root)

    removed: list[str] = []
    monkeypatch.setattr(orch.registry, "remove_entry", lambda p: removed.append(str(p)))
    monkeypatch.setattr(orch.registry, "upsert_entry", lambda *a, **k: None)

    await orch.run_rehome(state_dir, new_root, stores=orch.RehomeStores())
    assert removed == [str(old_root)]  # old ghost dropped


@pytest.mark.asyncio
async def test_copy_keeps_original_registry_entry(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    old_root = tmp_path / "original"  # STILL exists => a copy
    old_root.mkdir()
    new_root = tmp_path / "copy"
    new_root.mkdir()
    _seed_pending_move(state_dir, old_root, new_root)

    removed: list[str] = []
    upserted: list[str] = []
    monkeypatch.setattr(orch.registry, "remove_entry", lambda p: removed.append(str(p)))
    monkeypatch.setattr(
        orch.registry, "upsert_entry", lambda root, sd: upserted.append(str(root))
    )

    await orch.run_rehome(state_dir, new_root, stores=orch.RehomeStores())
    assert removed == []  # original NOT de-registered
    assert upserted == [str(new_root)]  # copy still registers itself
