"""Plan B Task 4 — session extraction links file mentions onto code nodes."""

from __future__ import annotations

from typing import Any

import pytest

from brainpalace_server.models.session_extract import SessionExtraction
from brainpalace_server.services.session_extract_service import SessionExtractService

ROOT = "/repo"


class FakeEmbedder:
    async def embed_chunks(self, chunks: list[Any]) -> list[list[float]]:
        return [[0.0] for _ in chunks]


class FakeStorage:
    is_initialized = True

    async def delete_by_metadata(self, filters: dict[str, Any]) -> None:
        return None

    async def upsert_documents(self, **kwargs: Any) -> None:
        return None


class FakeGraph:
    """Records add_triplet kwargs; answers the resolver's two lookups."""

    def __init__(self, nodes: dict[str, dict[str, Any]]) -> None:
        self._nodes = nodes
        self.calls: list[dict[str, Any]] = []

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        return self._nodes.get(node_id)

    def nodes_by_exact_name(
        self, name: str, domains: list[str] | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        return [n for n in self._nodes.values() if n["name"] == name][:limit]

    def add_triplet(self, subject: str, predicate: str, obj: str, **kw: Any) -> bool:
        self.calls.append(
            {"subject": subject, "predicate": predicate, "obj": obj, **kw}
        )
        return True

    def invalidate_by_source_file(self, source_file: str, domain: str = "code") -> int:
        return 0

    def sweep_orphan_nodes(self, domain: str = "code") -> int:
        return 0


def _payload(triplets: list[dict[str, str]]) -> SessionExtraction:
    return SessionExtraction.model_validate(
        {
            "session_id": "s1",
            "summary": "did things",
            "decisions": [],
            "triplets": triplets,
        }
    )


@pytest.mark.asyncio
async def test_resolved_file_mention_links_to_code_node() -> None:
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
    await SessionExtractService().store(
        _payload(
            [{"subject": "src/auth.py", "relation": "touches", "object": "login flow"}]
        ),
        embedder=FakeEmbedder(),
        storage_backend=FakeStorage(),
        graph_store=graph,
        project_root=ROOT,
    )
    (call,) = graph.calls
    assert call["subject_id"] == "/repo/src/auth.py"
    assert call["subject_domain"] == "code"
    assert call["subject_type"] == "File"
    assert call["edge_properties"] == {"resolved": True}
    assert call["domain"] == "session"
    assert call["source_file"] == "session:s1"


@pytest.mark.asyncio
async def test_unresolved_mention_keeps_current_behavior() -> None:
    graph = FakeGraph({})
    await SessionExtractService().store(
        _payload(
            [{"subject": "src/ghost.py", "relation": "touches", "object": "an idea"}]
        ),
        embedder=FakeEmbedder(),
        storage_backend=FakeStorage(),
        graph_store=graph,
        project_root=ROOT,
    )
    (call,) = graph.calls
    assert call["subject"] == "src/ghost.py"  # canonicalised rel path node
    assert "subject_id" not in call
    assert "edge_properties" not in call
    assert call["subject_type"] == "File"  # types_for('touches') unchanged


@pytest.mark.asyncio
async def test_decision_endpoints_never_resolve() -> None:
    # 'login' exists as a code Function — but a Decision endpoint must not link.
    graph = FakeGraph(
        {
            "/repo/src/auth.py:login": {
                "id": "/repo/src/auth.py:login",
                "name": "login",
                "label": "Function",
                "domain": "code",
            }
        }
    )
    await SessionExtractService().store(
        _payload(
            [{"subject": "login", "relation": "superseded-by", "object": "login"}]
        ),
        embedder=FakeEmbedder(),
        storage_backend=FakeStorage(),
        graph_store=graph,
        project_root=ROOT,
    )
    (call,) = graph.calls
    assert "subject_id" not in call and "object_id" not in call
