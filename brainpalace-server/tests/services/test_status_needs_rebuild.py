"""Plan 4 Task 7 — status exposes the pending one-time identity rebuild."""

import pytest

from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.services.indexing_service import IndexingService
from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.mark.asyncio
async def test_graph_index_status_has_needs_identity_rebuild(tmp_path):
    store_mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    store_mgr.initialize()
    svc = IndexingService.__new__(IndexingService)
    svc.graph_index_manager = GraphIndexManager(graph_store=store_mgr)

    flag = svc._graph_needs_identity_rebuild()
    assert flag is True
    store_mgr.mark_code_identity_rebuilt()
    assert svc._graph_needs_identity_rebuild() is False
