"""Plan B Task 5 — provider doc adapter resolves mentions onto code nodes."""

from __future__ import annotations

from typing import Any

import pytest

from brainpalace_server.services.doc_extraction_adapter import DocExtractionAdapter


class FakeGraph:
    def __init__(self, nodes: dict[str, dict[str, Any]]) -> None:
        self._nodes = nodes
        self.calls: list[dict[str, Any]] = []

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        return self._nodes.get(node_id)

    def nodes_by_exact_name(
        self, name: str, domains: list[str] | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        return [n for n in self._nodes.values() if n["name"] == name][:limit]

    def add_triplet(self, **kw: Any) -> bool:
        self.calls.append(kw)
        return True

    def invalidate_by_source_file(self, source_file: str, domain: str = "code") -> int:
        return 0

    def sweep_orphan_nodes(self, domain: str = "code") -> int:
        return 0

    def persist(self) -> None:
        return None


class FakeStore:
    def __init__(self) -> None:
        self.done: list[str] = []

    def mark_done(self, chunk_id: str) -> None:
        self.done.append(chunk_id)


class _T:
    def __init__(self, subject: str, obj: str) -> None:
        self.subject = subject
        self.predicate = "references"
        self.object = obj
        self.subject_type = "DesignDoc"
        self.object_type = "File"
        self.source_chunk_id = "chunk_x"


@pytest.mark.asyncio
async def test_provider_path_links_resolved_object(monkeypatch) -> None:
    graph = FakeGraph(
        {
            "/repo/src/auth.py": {
                "id": "/repo/src/auth.py",
                "name": "auth.py",
                "label": "File",
                "domain": "code",
            }
        }
    )
    adapter = DocExtractionAdapter(
        store=FakeStore(),
        graph_store=graph,
        provider_factory=lambda: object(),
        project_root="/repo",
    )

    async def fake_extract(
        text: str, chunk_id: str, *, provider: Any, max_triplets: int
    ):
        return [_T("Auth design", "src/auth.py")]

    monkeypatch.setattr(
        "brainpalace_server.services.doc_extraction_adapter.extract_doc_triplets",
        fake_extract,
    )
    assert await adapter.process(("chunk_x", "text")) is True
    (call,) = graph.calls
    assert call["object_id"] == "/repo/src/auth.py"
    assert call["object_domain"] == "code"
    assert call["edge_properties"] == {"resolved": True}
    assert call["domain"] == "doc"
    assert call["source_file"] == "chunk_x"
