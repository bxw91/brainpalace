import pytest

from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture
def mgr(tmp_path):
    m = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    m.initialize()
    return m


def test_needs_rebuild_true_then_false_after_mark(mgr):
    assert mgr.needs_code_identity_rebuild() is True
    mgr.mark_code_identity_rebuilt()
    assert mgr.needs_code_identity_rebuild() is False
