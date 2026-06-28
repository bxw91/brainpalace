from unittest.mock import patch

from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.extraction_pending import DocPendingStore


def test_doc_chunk_marked_pending_not_extracted_inline(tmp_path):
    pending = DocPendingStore(tmp_path / "p.db")
    mgr = GraphIndexManager(pending_store=pending)
    docs = [
        {
            "text": "BrainPalace uses BM25.",
            "metadata": {"source_type": "document"},
            "id": "d1",
        },
    ]
    with patch("brainpalace_server.indexing.graph_index.settings") as s:
        s.ENABLE_GRAPH_INDEX = True
        s.GRAPH_USE_CODE_METADATA = True
        mgr.build_from_documents(docs)
    # Doc chunk is queued for async drain, not turned into triplets synchronously.
    assert pending.select_pending(10) == [("d1", "BrainPalace uses BM25.")]


def test_git_commit_chunk_tagged_git_kind(tmp_path):
    pending = DocPendingStore(tmp_path / "p.db")
    mgr = GraphIndexManager(pending_store=pending)
    docs = [
        {"text": "fix bug", "metadata": {"source_type": "git_commit"}, "id": "g1"},
        {"text": "readme", "metadata": {"source_type": "document"}, "id": "d1"},
    ]
    with patch("brainpalace_server.indexing.graph_index.settings") as s:
        s.ENABLE_GRAPH_INDEX = True
        s.GRAPH_USE_CODE_METADATA = True
        mgr.build_from_documents(docs)
    # Git-commit chunks count under "git", doc chunks under "doc" — separate rows.
    assert pending.count_pending(kind="git") == 1
    assert pending.count_pending(kind="doc") == 1
    assert pending.count_pending() == 2  # unfiltered = both


def test_code_chunk_still_synchronous(tmp_path):
    pending = DocPendingStore(tmp_path / "p.db")
    mgr = GraphIndexManager(pending_store=pending)
    docs = [
        {
            "text": "x",
            "metadata": {"source_type": "code", "symbol_name": "f"},
            "id": "c1",
        },
    ]
    with patch("brainpalace_server.indexing.graph_index.settings") as s:
        s.ENABLE_GRAPH_INDEX = True
        s.GRAPH_USE_CODE_METADATA = True
        mgr.build_from_documents(docs)
    assert pending.count_pending() == 0  # code path is not deferred
