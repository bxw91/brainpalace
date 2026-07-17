# tests/rehome/test_identity.py
import pytest

from brainpalace_server.rehome.identity import (
    IdentityCorruptError,
    ProjectIdentity,
    ensure_identity,
    load_identity,
    write_identity,
)


def test_load_absent_returns_none(tmp_path):
    assert load_identity(tmp_path) is None


def test_ensure_backfills_and_persists(tmp_path):
    ident = ensure_identity(tmp_path, tmp_path)
    assert ident.project_uuid
    assert ident.indexed_root == str(tmp_path.resolve())
    # persisted + stable across calls
    again = ensure_identity(tmp_path, tmp_path)
    assert again.project_uuid == ident.project_uuid


def test_write_then_load_roundtrips(tmp_path):
    ident = ProjectIdentity(project_uuid="u1", indexed_root="/x/y")
    write_identity(tmp_path, ident)
    assert load_identity(tmp_path) == ident
    # No lineage by default.
    assert ident.parent_uuid is None
    assert ident.parent_index_root is None


def test_write_then_load_roundtrips_with_lineage(tmp_path):
    """Part B: parent_uuid / parent_index_root survive a write→load round-trip."""
    ident = ProjectIdentity(
        project_uuid="u2",
        indexed_root="/new/root",
        parent_uuid="u1",
        parent_index_root="/old/root",
    )
    write_identity(tmp_path, ident)
    loaded = load_identity(tmp_path)
    assert loaded == ident
    assert loaded is not None
    assert loaded.parent_uuid == "u1"
    assert loaded.parent_index_root == "/old/root"


def test_load_old_identity_without_lineage_fields(tmp_path):
    """An identity.json written before Part B (no parent_* keys) loads as
    "no parent" — backward compatible, not corrupt."""
    import json as _json

    (tmp_path / "identity.json").write_text(
        _json.dumps({"project_uuid": "u1", "indexed_root": "/x/y"})
    )
    loaded = load_identity(tmp_path)
    assert loaded == ProjectIdentity(project_uuid="u1", indexed_root="/x/y")
    assert loaded.parent_uuid is None
    assert loaded.parent_index_root is None


def test_ensure_backfill_has_no_parent(tmp_path):
    """A first-seen backfilled identity has no lineage (parent_* = None)."""
    ident = ensure_identity(tmp_path, tmp_path)
    assert ident.parent_uuid is None
    assert ident.parent_index_root is None


def test_corrupt_identity_raises(tmp_path):
    (tmp_path / "identity.json").write_text("{broken")
    with pytest.raises(IdentityCorruptError):
        load_identity(tmp_path)


def test_write_identity_lands_in_state_subfolder(tmp_path):
    """C2: identity.json now lives under state_dir/state/, not state_dir root."""
    ident = ProjectIdentity(project_uuid="u1", indexed_root="/x/y")
    write_identity(tmp_path, ident)
    assert (tmp_path / "state" / "identity.json").exists()
    assert not (tmp_path / "identity.json").exists()


def test_migrate_legacy_root_identity_preserves_lineage_no_remint(tmp_path):
    """C1: a pre-C2 root-level identity.json (incl. Part B lineage fields)
    migrates atomically into state/ on load — uuid AND parent_uuid/
    parent_index_root preserved, and ensure_identity does NOT re-mint a fresh
    uuid over the migrated one."""
    import json as _json

    (tmp_path / "identity.json").write_text(
        _json.dumps(
            {
                "project_uuid": "child-uuid",
                "indexed_root": "/new/root",
                "parent_uuid": "parent-uuid",
                "parent_index_root": "/old/root",
            }
        )
    )

    loaded = load_identity(tmp_path)

    assert loaded is not None
    assert loaded.project_uuid == "child-uuid"
    assert loaded.indexed_root == "/new/root"
    assert loaded.parent_uuid == "parent-uuid"
    assert loaded.parent_index_root == "/old/root"
    # Migrated: old root file gone, new state/ file present.
    assert not (tmp_path / "identity.json").exists()
    assert (tmp_path / "state" / "identity.json").exists()
    # ensure_identity must NOT re-mint — the migrated identity already exists.
    again = ensure_identity(tmp_path, tmp_path)
    assert again.project_uuid == "child-uuid"
    assert again.parent_uuid == "parent-uuid"


def test_migrate_is_noop_once_new_path_exists(tmp_path):
    """If state/identity.json already exists, a stray root-level file (e.g. left
    over from a previous partial migration or a fresh write) must NOT overwrite
    it or be silently consumed."""
    import json as _json

    write_identity(tmp_path, ProjectIdentity(project_uuid="new", indexed_root="/n"))
    (tmp_path / "identity.json").write_text(
        _json.dumps({"project_uuid": "old", "indexed_root": "/o"})
    )

    loaded = load_identity(tmp_path)

    assert loaded is not None
    assert loaded.project_uuid == "new"
    # The stray root file is left untouched (migration only fires when the new
    # path is absent).
    assert (tmp_path / "identity.json").exists()
