# tests/rehome/test_state.py
import pytest

from brainpalace_server.rehome.state import (
    RehomeStateCorruptError,
    load_rehome_state,
    new_rehome_state,
    write_rehome_state,
)


def test_load_absent_returns_none(tmp_path):
    assert load_rehome_state(tmp_path) is None


def test_new_state_defaults(tmp_path):
    st = new_rehome_state("u1", "/old", "/new")
    assert st.status == "pending" and st.phase == 1 and st.cursor is None
    assert st.started_at and st.updated_at


def test_write_load_roundtrip_and_updated_at_stamped(tmp_path):
    st = new_rehome_state("u1", "/old", "/new")
    old_updated = st.updated_at
    st.status = "in_progress"
    st.phase = 3
    write_rehome_state(tmp_path, st)
    loaded = load_rehome_state(tmp_path)
    assert loaded is not None
    assert loaded.status == "in_progress" and loaded.phase == 3
    assert loaded.updated_at >= old_updated


def test_corrupt_state_raises(tmp_path):
    (tmp_path / "rehome.json").write_text("{broken")
    with pytest.raises(RehomeStateCorruptError):
        load_rehome_state(tmp_path)
