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


def test_sentinel_no_rehome_state_returns_none(tmp_path):
    write_identity(
        tmp_path, ProjectIdentity(project_uuid="u", indexed_root=str(tmp_path))
    )
    ident, move = orch._validate_sentinels(tmp_path, tmp_path)
    assert ident.project_uuid == "u"
    assert move is None  # unmoved, no rehome.json
