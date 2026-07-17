"""Part B — uuid + root lineage on rehome (DB1/DB2, B2/B4, hardening #5).

Every rehome mints a FRESH project_uuid at finalize and records
parent_uuid / parent_index_root, so a chain A -> B -> C stays traceable with
each link a distinct, honest id. The mint is idempotent across a resume that
re-enters finalize (never a second uuid, no spurious hop), and a mid-flip
resume — where identity already carries the new uuid but rehome.json still
carries the parent — is accepted and completed, not refused.
"""

from __future__ import annotations

import os

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


@pytest.fixture
def _stub_registry(monkeypatch):
    """Finalize's registry remap is a real side effect — stub it out."""
    monkeypatch.setattr(orch.registry, "remove_entry", lambda *a, **k: None)
    monkeypatch.setattr(orch.registry, "upsert_entry", lambda *a, **k: None)


@pytest.mark.asyncio
async def test_chain_a_b_c_mints_and_chains_lineage(tmp_path, _stub_registry):
    """B2/B4: each hop A->B->C mints a NEW uuid; parent_uuid / parent_index_root
    point at the immediately prior hop (chain deepens by exactly one)."""
    state_dir = tmp_path / "state"
    a = tmp_path / "a"
    b = tmp_path / "b"
    c = tmp_path / "c"
    for d in (state_dir, a, b, c):
        d.mkdir()

    # First-seen identity at A: no parent.
    write_identity(state_dir, ProjectIdentity(project_uuid="uA", indexed_root=str(a)))

    # Move A -> B (detect_move fires: current_root b != indexed_root a).
    res1 = await orch.run_rehome(state_dir, b, stores=orch.RehomeStores())
    assert res1.status == "done"
    id1 = load_identity(state_dir)
    assert id1 is not None
    assert id1.project_uuid != "uA"  # fresh mint, not inherited
    assert id1.parent_uuid == "uA"
    assert id1.parent_index_root == os.path.realpath(str(a))
    assert id1.indexed_root == os.path.realpath(str(b))
    u_b = id1.project_uuid
    # rehome.json advanced to the new uuid (steady state) and recorded it minted.
    st1 = load_rehome_state(state_dir)
    assert st1 is not None
    assert st1.project_uuid == u_b
    assert st1.minted_uuid == u_b

    # Move B -> C: chains one deeper.
    res2 = await orch.run_rehome(state_dir, c, stores=orch.RehomeStores())
    assert res2.status == "done"
    id2 = load_identity(state_dir)
    assert id2 is not None
    assert id2.project_uuid != u_b  # a distinct third uuid
    assert id2.parent_uuid == u_b  # parent is B, not the original A
    assert id2.parent_index_root == os.path.realpath(str(b))
    assert id2.indexed_root == os.path.realpath(str(c))
    # No stale minted_uuid carried over from the A->B state (B4).
    st2 = load_rehome_state(state_dir)
    assert st2 is not None
    assert st2.minted_uuid == id2.project_uuid


@pytest.mark.asyncio
async def test_resume_mid_flip_reuses_minted_uuid_and_completes(
    tmp_path, _stub_registry
):
    """Hardening #5 + B1: a crash between the identity write and the rehome.json
    write leaves identity on the NEW uuid (parent = old) while rehome.json still
    carries the parent uuid and the already-persisted minted_uuid. Resume must:
    be ACCEPTED (not refused), reuse the persisted minted_uuid (no second mint,
    no extra hop), and complete the flip to done."""
    state_dir = tmp_path / "state"
    home = tmp_path / "home"
    old = tmp_path / "old"
    for d in (state_dir, home, old):
        d.mkdir()

    # Identity already flipped to the new uuid (crash was AFTER step 2).
    write_identity(
        state_dir,
        ProjectIdentity(
            project_uuid="uNEW",
            indexed_root=str(home),
            parent_uuid="uOLD",
            parent_index_root=str(old),
        ),
    )
    # rehome.json still on the parent uuid, minted_uuid already persisted (step 1
    # ran), status in_progress at the final phase (crash before step 3).
    mid = new_rehome_state("uOLD", str(old), str(home))
    mid.minted_uuid = "uNEW"
    mid.status = "in_progress"
    mid.phase = 6
    write_rehome_state(state_dir, mid)

    # current_root == identity home => no NEW move; this is a pure resume.
    result = await orch.run_rehome(state_dir, home, stores=orch.RehomeStores())

    assert result.status == "done"
    id_after = load_identity(state_dir)
    assert id_after is not None
    # Reused the persisted minted uuid — NOT a freshly minted second uuid.
    assert id_after.project_uuid == "uNEW"
    # Chain depth unchanged: parent is still the single original parent.
    assert id_after.parent_uuid == "uOLD"
    assert id_after.parent_index_root == str(old)
    # rehome.json completed the flip to the new uuid.
    st_after = load_rehome_state(state_dir)
    assert st_after is not None
    assert st_after.project_uuid == "uNEW"
    assert st_after.minted_uuid == "uNEW"


@pytest.mark.asyncio
async def test_foreign_rehome_json_uuid_refused_at_run(tmp_path, _stub_registry):
    """A rehome.json uuid that is neither the identity's uuid nor its parent is
    genuinely foreign — run_rehome refuses (B1 relaxation is parent-or-self only)."""
    state_dir = tmp_path / "state"
    home = tmp_path / "home"
    for d in (state_dir, home):
        d.mkdir()

    write_identity(
        state_dir,
        ProjectIdentity(
            project_uuid="uNEW", indexed_root=str(home), parent_uuid="uOLD"
        ),
    )
    foreign = new_rehome_state("uFOREIGN", str(home), str(home))
    write_rehome_state(state_dir, foreign)

    with pytest.raises(orch.RehomeRefused):
        await orch.run_rehome(state_dir, home, stores=orch.RehomeStores())
