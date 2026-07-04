"""Plan 4 Task 4 — a cross-domain edge must not flip the code node's domain."""

import pytest

from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture
def mgr(tmp_path):
    m = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    m.initialize()
    return m


def _domains(mgr):
    return dict(
        mgr._graph_store._conn.execute("SELECT id, domain FROM nodes").fetchall()
    )


def test_object_domain_preserves_code_node(mgr):
    mgr.add_triplet(
        "a",
        "calls",
        "b",
        subject_id="f.py:a",
        object_id="f.py:b",
        subject_name="a",
        object_name="b",
        source_file="f.py",
        domain="code",
    )
    # A doc-domain edge that LINKS to the code node (Spec B/C shape):
    mgr.add_triplet(
        "alpha doc",
        "references",
        "a",
        subject_id="doc:alpha",
        object_id="f.py:a",
        subject_name="alpha doc",
        object_name="a",
        source_file="c1",
        domain="doc",
        object_domain="code",
    )
    domains = _domains(mgr)
    assert domains["f.py:a"] == "code"  # NOT flipped to doc
    assert domains["doc:alpha"] == "doc"


def test_default_stays_single_domain(mgr):
    mgr.add_triplet(
        "x",
        "references",
        "y",
        source_chunk_id="c2",
        source_file="c2",
        domain="doc",
    )
    domains = _domains(mgr)
    assert domains["x"] == "doc" and domains["y"] == "doc"
