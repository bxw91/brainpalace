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
    # Part B: no uuid minted until finalize.
    assert st.minted_uuid is None


def test_minted_uuid_roundtrips(tmp_path):
    """Part B: minted_uuid survives a write→load round-trip so a resume can
    reuse it instead of minting a second uuid."""
    st = new_rehome_state("u1", "/old", "/new")
    st.minted_uuid = "newuuid"
    write_rehome_state(tmp_path, st)
    loaded = load_rehome_state(tmp_path)
    assert loaded is not None
    assert loaded.minted_uuid == "newuuid"


def test_load_old_state_without_minted_uuid(tmp_path):
    """A rehome.json written before Part B (no minted_uuid key) loads as
    "not yet minted" — backward compatible, not corrupt."""
    import json as _json

    (tmp_path / "rehome.json").write_text(
        _json.dumps(
            {
                "project_uuid": "u1",
                "old_root": "/old",
                "new_root": "/new",
                "status": "in_progress",
                "phase": 3,
                "cursor": None,
                "error": None,
                "started_at": "t0",
                "updated_at": "t1",
            }
        )
    )
    loaded = load_rehome_state(tmp_path)
    assert loaded is not None
    assert loaded.minted_uuid is None
    assert loaded.project_uuid == "u1" and loaded.phase == 3


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


def test_write_state_lands_in_state_subfolder(tmp_path):
    """C2: rehome.json now lives under state_dir/state/, not state_dir root."""
    st = new_rehome_state("u1", "/old", "/new")
    write_rehome_state(tmp_path, st)
    assert (tmp_path / "state" / "rehome.json").exists()
    assert not (tmp_path / "rehome.json").exists()


def test_migrate_legacy_root_rehome_state_preserves_fields(tmp_path):
    """C1: a pre-C2 root-level rehome.json (incl. Part B's minted_uuid) migrates
    atomically into state/ on load, with every field preserved."""
    import json as _json

    (tmp_path / "rehome.json").write_text(
        _json.dumps(
            {
                "project_uuid": "u1",
                "old_root": "/old",
                "new_root": "/new",
                "status": "in_progress",
                "phase": 3,
                "cursor": "c9",
                "error": None,
                "started_at": "t0",
                "updated_at": "t1",
                "minted_uuid": "minted-1",
            }
        )
    )

    loaded = load_rehome_state(tmp_path)

    assert loaded is not None
    assert loaded.project_uuid == "u1" and loaded.phase == 3
    assert loaded.cursor == "c9"
    assert loaded.minted_uuid == "minted-1"
    # Migrated: old root file gone, new state/ file present.
    assert not (tmp_path / "rehome.json").exists()
    assert (tmp_path / "state" / "rehome.json").exists()


def test_migrate_is_noop_once_new_path_exists(tmp_path):
    """If state/rehome.json already exists, a stray root-level file must NOT
    overwrite it or be silently consumed."""
    import json as _json

    write_rehome_state(tmp_path, new_rehome_state("new", "/o", "/n"))
    (tmp_path / "rehome.json").write_text(
        _json.dumps(
            {
                "project_uuid": "old",
                "old_root": "/o",
                "new_root": "/n",
                "status": "pending",
                "phase": 1,
                "cursor": None,
                "error": None,
                "started_at": "t0",
                "updated_at": "t0",
            }
        )
    )

    loaded = load_rehome_state(tmp_path)

    assert loaded is not None
    assert loaded.project_uuid == "new"
    assert (tmp_path / "rehome.json").exists()
