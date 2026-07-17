import pytest

from brainpalace_server.rehome import orchestrator as orch
from brainpalace_server.rehome.identity import ProjectIdentity, write_identity
from brainpalace_server.rehome.state import new_rehome_state, write_rehome_state


def test_sentinel_uuid_mismatch_refused(tmp_path):
    write_identity(
        tmp_path, ProjectIdentity(project_uuid="uuid-A", indexed_root=str(tmp_path))
    )
    st = new_rehome_state("uuid-B", str(tmp_path), str(tmp_path))  # foreign uuid
    write_rehome_state(tmp_path, st)
    with pytest.raises(orch.RehomeRefused):
        orch._validate_sentinels(tmp_path, tmp_path)


def test_sentinel_accepts_parent_uuid_mid_flip(tmp_path):
    """B1: mid-flip / resume across the finalize mint — identity already carries
    the NEW uuid with parent_uuid = the previous one, while rehome.json still
    carries that parent uuid. Accept (not refuse); resume completes the flip."""
    write_identity(
        tmp_path,
        ProjectIdentity(
            project_uuid="uuid-NEW",
            indexed_root=str(tmp_path),
            parent_uuid="uuid-OLD",
            parent_index_root="/old/root",
        ),
    )
    st = new_rehome_state("uuid-OLD", str(tmp_path), str(tmp_path))  # the parent uuid
    write_rehome_state(tmp_path, st)
    ident, _move = orch._validate_sentinels(tmp_path, tmp_path)
    assert ident.project_uuid == "uuid-NEW"


def test_sentinel_foreign_uuid_still_refused_with_parent_set(tmp_path):
    """A uuid that is neither self nor parent is still foreign — refused even
    when a parent_uuid is present."""
    write_identity(
        tmp_path,
        ProjectIdentity(
            project_uuid="uuid-NEW",
            indexed_root=str(tmp_path),
            parent_uuid="uuid-OLD",
        ),
    )
    st = new_rehome_state("uuid-FOREIGN", str(tmp_path), str(tmp_path))
    write_rehome_state(tmp_path, st)
    with pytest.raises(orch.RehomeRefused):
        orch._validate_sentinels(tmp_path, tmp_path)


def test_sentinel_no_rehome_state_returns_none(tmp_path):
    write_identity(
        tmp_path, ProjectIdentity(project_uuid="u", indexed_root=str(tmp_path))
    )
    ident, move = orch._validate_sentinels(tmp_path, tmp_path)
    assert ident.project_uuid == "u"
    assert move is None  # unmoved, no rehome.json
