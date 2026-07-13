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


def test_corrupt_identity_raises(tmp_path):
    (tmp_path / "identity.json").write_text("{broken")
    with pytest.raises(IdentityCorruptError):
        load_identity(tmp_path)
