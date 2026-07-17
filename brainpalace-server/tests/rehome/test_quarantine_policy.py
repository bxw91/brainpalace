from brainpalace_server.rehome import quarantine as q
from brainpalace_server.rehome.identity import ProjectIdentity, write_identity
from brainpalace_server.rehome.state import new_rehome_state, write_rehome_state


def test_allowlist_gate():
    assert q.is_request_allowed("/health")
    assert q.is_request_allowed("/health/status")
    assert q.is_request_allowed("/runtime")
    assert q.is_request_allowed("/rehome/")
    assert q.is_request_allowed("/rehome/resume")
    assert q.is_request_allowed("/")
    assert q.is_request_allowed("/openapi.json")
    assert not q.is_request_allowed("/query")
    assert not q.is_request_allowed("/index/folders")
    assert not q.is_request_allowed("/healthful")  # prefix must be a real segment


def test_evaluate_fresh_backfills_no_rehome(tmp_path):
    plan = q.evaluate_startup(tmp_path, tmp_path)  # no identity.json yet -> backfill
    assert plan.identity.indexed_root  # adopted current root
    assert plan.needs_rehome is False
    assert plan.existing is None
    assert plan.move is None


def test_evaluate_detects_move(tmp_path):
    write_identity(tmp_path, ProjectIdentity("u", "/old/root"))
    plan = q.evaluate_startup(tmp_path, tmp_path)  # current_root=tmp_path != /old/root
    assert plan.needs_rehome is True
    assert plan.move is not None
    assert plan.stale_done is False


def test_evaluate_pending_rehome_needs_run(tmp_path):
    write_identity(tmp_path, ProjectIdentity("u", str(tmp_path)))
    st = new_rehome_state("u", str(tmp_path), "/new")
    st.status = "failed"
    write_rehome_state(tmp_path, st)
    plan = q.evaluate_startup(tmp_path, tmp_path)
    assert plan.needs_rehome is True
    assert plan.existing is not None and plan.existing.status == "failed"


def test_evaluate_done_and_unmoved_is_noop(tmp_path):
    write_identity(tmp_path, ProjectIdentity("u", str(tmp_path)))
    st = new_rehome_state("u", "/old", str(tmp_path))
    st.status = "done"
    write_rehome_state(tmp_path, st)
    plan = q.evaluate_startup(tmp_path, tmp_path)  # identity already at current root
    assert plan.needs_rehome is False
    assert plan.stale_done is False


def test_clear_stale_rehome_state_removes_relocated_file(tmp_path):
    """C2: rehome.json lives under state_dir/state/ now. clear_stale_rehome_state
    must resolve that same path (via state.py's _path) rather than hand-building
    the old root path, or a stale done-state would silently survive a second
    move."""
    st = new_rehome_state("u", "/old", str(tmp_path))
    st.status = "done"
    write_rehome_state(tmp_path, st)
    assert (tmp_path / "state" / "rehome.json").exists()

    q.clear_stale_rehome_state(tmp_path)

    assert not (tmp_path / "state" / "rehome.json").exists()


def test_clear_stale_rehome_state_is_noop_when_absent(tmp_path):
    """No rehome.json anywhere -> no error."""
    q.clear_stale_rehome_state(tmp_path)  # must not raise
