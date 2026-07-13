# tests/rehome/test_orchestrator_second_move.py
"""Second-move-after-done: run_rehome must re-run for a NEW move even though the
recorded rehome.json is status=done (previously it early-returned and ignored the
new move)."""

import pytest

from brainpalace_server.rehome import orchestrator as orch
from brainpalace_server.rehome.identity import (
    ProjectIdentity,
    load_identity,
    write_identity,
)
from brainpalace_server.rehome.state import (
    load_rehome_state,
    new_rehome_state,
    write_rehome_state,
)


@pytest.mark.asyncio
async def test_second_move_after_done_reruns(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    root1 = tmp_path / "r1"
    root2 = tmp_path / "r2"
    root1.mkdir()
    root2.mkdir()

    # Identity home is root1; a PRIOR rehome (root0 -> root1) already completed.
    write_identity(state_dir, ProjectIdentity("u", str(root1)))
    done = new_rehome_state("u", str(tmp_path / "r0"), str(root1))
    done.status = "done"
    write_rehome_state(state_dir, done)

    # Registry remap is a real side effect at finalize — stub it.
    monkeypatch.setattr(orch.registry, "remove_entry", lambda *a, **k: None)
    monkeypatch.setattr(orch.registry, "upsert_entry", lambda *a, **k: None)

    # A NEW move root1 -> root2. All stores None => phases no-op, but the state
    # machine must still run + finalize for the new move (not early-return).
    result = await orch.run_rehome(state_dir, root2, stores=orch.RehomeStores())

    assert result.status == "done"
    assert result.new_root == str(root2)
    assert result.old_root == str(root1)  # the fresh move, not the stale one
    # rehome.json persisted the new move; identity now homes at root2.
    persisted = load_rehome_state(state_dir)
    assert persisted is not None and persisted.new_root == str(root2)
    assert load_identity(state_dir).indexed_root == str(root2)


@pytest.mark.asyncio
async def test_done_and_unmoved_still_early_returns(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    root1 = tmp_path / "r1"
    root1.mkdir()
    write_identity(state_dir, ProjectIdentity("u", str(root1)))
    done = new_rehome_state("u", str(tmp_path / "r0"), str(root1))
    done.status = "done"
    write_rehome_state(state_dir, done)

    # current_root == identity home => no new move => nothing to do.
    result = await orch.run_rehome(state_dir, root1, stores=orch.RehomeStores())
    assert result.status == "done"
    assert result.new_root == str(root1)  # unchanged; the original done-state
