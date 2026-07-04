"""Plan 4 Task 3 — purging one source must not reset every source's dedup."""

import pytest

from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture
def mgr(tmp_path):
    m = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    m.initialize()
    return m


_CODE = {
    "subject_id": "f.py:a",
    "object_id": "f.py:b",
    "subject_name": "a",
    "object_name": "b",
    "source_file": "f.py",
    "domain": "code",
}


def test_purge_clears_dedup_only_for_that_source(mgr):
    assert mgr.add_triplet("a", "calls", "b", **_CODE) is True
    assert (
        mgr.add_triplet(
            "X",
            "references",
            "Y",
            source_chunk_id="c9",
            source_file="c9",
            domain="doc",
        )
        is True
    )
    mgr.invalidate_by_source_file("f.py", domain="code")
    # The purged file may rewrite its identical triplet...
    assert mgr.add_triplet("a", "calls", "b", **_CODE) is True
    # ...but an unrelated chunk's resubmit stays deduped (H4/E4 intact).
    assert (
        mgr.add_triplet(
            "X",
            "references",
            "Y",
            source_chunk_id="c9",
            source_file="c9",
            domain="doc",
        )
        is False
    )
