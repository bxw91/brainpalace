"""ENABLE_GRAPH_INDEX gates BUILDING the graph, not the query.

A graph query with the graph disabled returns empty — like bm25/vector on an
empty index — instead of raising. The build cost stays gated; query
availability is separated from the feature switch.
"""

import pytest

from brainpalace_server.models.query import QueryMode, QueryRequest
from brainpalace_server.services.query_service import QueryService


@pytest.mark.asyncio
async def test_graph_query_returns_empty_when_disabled(monkeypatch):
    from brainpalace_server.config import settings

    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", False)
    monkeypatch.setattr(
        "brainpalace_server.storage.get_effective_backend_type",
        lambda: "chroma",  # pass the backend-compat check
    )
    svc = QueryService()
    request = QueryRequest(query="who calls foo", mode=QueryMode.GRAPH)

    # Does not raise; empty because no graph is built.
    result = await svc._execute_graph_query(request)
    assert result == []
