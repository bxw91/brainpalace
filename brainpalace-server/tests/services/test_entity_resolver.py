"""Plan B Task 3 — deterministic mention→code-node resolver (pure)."""

from __future__ import annotations

from typing import Any

from brainpalace_server.services.entity_resolver import (
    ResolvedEntity,
    link_kwargs,
    resolve_entity,
)

ROOT = "/repo"


class FakeGraph:
    """Duck-typed stand-in for GraphStoreManager (get_node + exact-name)."""

    def __init__(self, nodes: list[dict[str, Any]]) -> None:
        self._nodes = {n["id"]: n for n in nodes}

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        return self._nodes.get(node_id)

    def nodes_by_exact_name(
        self, name: str, domains: list[str] | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        rows = [
            n
            for n in self._nodes.values()
            if n["name"] == name and (not domains or n["domain"] in domains)
        ]
        return rows[:limit]


def _graph() -> FakeGraph:
    return FakeGraph(
        [
            {
                "id": "/repo/src/auth.py",
                "name": "auth.py",
                "label": "File",
                "domain": "code",
            },
            {
                "id": "/repo/src/auth.py:login",
                "name": "login",
                "label": "Function",
                "domain": "code",
            },
            {
                "id": "/repo/src/a.py",
                "name": "dup.py",
                "label": "File",
                "domain": "code",
            },
            {
                "id": "/repo/src/b/dup.py",
                "name": "dup.py",
                "label": "File",
                "domain": "code",
            },
        ]
    )


# --- T1: path mentions -------------------------------------------------------


def test_t1_relative_path() -> None:
    r = resolve_entity("src/auth.py", None, ROOT, _graph())
    assert r == ResolvedEntity(id="/repo/src/auth.py", name="auth.py", label="File")


def test_t1_absolute_path() -> None:
    r = resolve_entity("/repo/src/auth.py", "File", ROOT, _graph())
    assert r is not None and r.id == "/repo/src/auth.py"


def test_t1_dot_slash_normalised() -> None:
    r = resolve_entity("./src/auth.py", None, ROOT, _graph())
    assert r is not None and r.id == "/repo/src/auth.py"


def test_path_outside_root_unresolved() -> None:
    assert resolve_entity("/elsewhere/auth.py", None, ROOT, _graph()) is None


def test_unknown_path_unresolved() -> None:
    assert resolve_entity("src/ghost.py", None, ROOT, _graph()) is None


def test_t1_doc_domain_node_never_resolves() -> None:
    # A doc chunk mentioning an unindexed abs path creates a doc-domain node
    # keyed by that path (the raw mention becomes the node id). A later
    # mention of the same path must NOT resolve through it — only a
    # domain='code' node counts, mirroring T3's domains=["code"] filter.
    graph = FakeGraph(
        [
            {
                "id": "/repo/src/unindexed.py",
                "name": "/repo/src/unindexed.py",
                "label": "File",
                "domain": "doc",
            },
        ]
    )
    assert resolve_entity("src/unindexed.py", None, ROOT, graph) is None
    assert resolve_entity("/repo/src/unindexed.py", "File", ROOT, graph) is None


# --- T2: path:fqname mentions ------------------------------------------------


def test_t2_symbol_mention() -> None:
    r = resolve_entity("src/auth.py:login", None, ROOT, _graph())
    assert r == ResolvedEntity(
        id="/repo/src/auth.py:login", name="login", label="Function"
    )


def test_t2_unknown_symbol_unresolved() -> None:
    assert resolve_entity("src/auth.py:ghost", None, ROOT, _graph()) is None


def test_t2_doc_domain_symbol_node_never_resolves() -> None:
    graph = FakeGraph(
        [
            {
                "id": "/repo/src/auth.py:login",
                "name": "login",
                "label": "Function",
                "domain": "doc",
            },
        ]
    )
    assert resolve_entity("src/auth.py:login", None, ROOT, graph) is None


# --- T3: unique exact display name -------------------------------------------


def test_t3_unique_identifier() -> None:
    r = resolve_entity("login", None, ROOT, _graph())
    assert r is not None and r.id == "/repo/src/auth.py:login"


def test_t3_basename_anywhere_in_tree() -> None:
    # 'auth.py' does not exist at <root>/auth.py (T1 misses), but the display
    # name is unique among code nodes → resolved via T3.
    r = resolve_entity("auth.py", None, ROOT, _graph())
    assert r is not None and r.id == "/repo/src/auth.py"


def test_t3_ambiguous_never_links() -> None:
    assert resolve_entity("dup.py", None, ROOT, _graph()) is None


def test_t3_free_text_never_links() -> None:
    assert resolve_entity("use the login flow", None, ROOT, _graph()) is None


def test_t3_short_mention_never_links() -> None:
    assert resolve_entity("a", None, ROOT, _graph()) is None


# --- guards -------------------------------------------------------------------


def test_session_only_types_never_resolve() -> None:
    for etype in ("Decision", "Error", "Session", "Tool", "Task"):
        assert resolve_entity("login", etype, ROOT, _graph()) is None


def test_empty_root_never_path_resolves() -> None:
    assert resolve_entity("src/auth.py", None, "", _graph()) is None


def test_graph_without_methods_degrades() -> None:
    class Bare:
        pass

    assert resolve_entity("src/auth.py", None, ROOT, Bare()) is None


def test_graph_raising_degrades() -> None:
    class Boom:
        def get_node(self, node_id: str):
            raise RuntimeError("db locked")

        def nodes_by_exact_name(self, name: str, domains=None, limit=10):
            raise RuntimeError("db locked")

    assert resolve_entity("src/auth.py", None, ROOT, Boom()) is None


# --- link_kwargs ---------------------------------------------------------------


def test_link_kwargs_object_resolved() -> None:
    kw = link_kwargs("fixed the bug", "src/auth.py", "Decision", "File", ROOT, _graph())
    assert kw == {
        "object_id": "/repo/src/auth.py",
        "object_name": "auth.py",
        "object_type": "File",
        "object_domain": "code",
        "edge_properties": {"resolved": True},
    }


def test_link_kwargs_both_resolved() -> None:
    kw = link_kwargs("src/auth.py", "login", "File", None, ROOT, _graph())
    assert kw["subject_id"] == "/repo/src/auth.py"
    assert kw["subject_domain"] == "code"
    assert kw["object_id"] == "/repo/src/auth.py:login"
    assert kw["object_type"] == "Function"
    assert kw["edge_properties"] == {"resolved": True}


def test_link_kwargs_nothing_resolved_is_empty() -> None:
    assert link_kwargs("idea", "concept", None, None, ROOT, _graph()) == {}
