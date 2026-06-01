"""LSP results → typed GraphTriples (Phase 150)."""

from __future__ import annotations

from brainpalace_server.lsp.cross_refs import extract_cross_refs


class FakeClient:
    """Returns canned results per LSP method (params ignored)."""

    def __init__(self, responses: dict) -> None:
        self.responses = responses

    def request(self, method, params=None):
        return self.responses.get(method)


def _loc(path: str, line: int) -> dict:
    return {"uri": f"file://{path}", "range": {"start": {"line": line, "character": 0}}}


def _ch_item(name: str, path: str, line: int = 0) -> dict:
    return {
        "name": name,
        "uri": f"file://{path}",
        "kind": 12,
        "range": {"start": {"line": line, "character": 0}},
    }


def _triples(client):
    return extract_cross_refs(
        client,
        file_path="pkg/mod.py",
        symbol_name="handler",
        line=10,
        character=4,
        source_chunk_id="c1",
    )


def test_defined_at_from_definition() -> None:
    client = FakeClient({"textDocument/definition": [_loc("pkg/mod.py", 9)]})
    triples = _triples(client)
    t = next(t for t in triples if t.predicate == "defined-at")
    assert t.subject == "pkg/mod.py:handler"
    assert t.object == "pkg/mod.py:10"  # 1-based line
    assert t.source_chunk_id == "c1"


def test_incoming_calls_become_calls_edges() -> None:
    client = FakeClient(
        {
            "textDocument/prepareCallHierarchy": [_ch_item("handler", "pkg/mod.py")],
            "callHierarchy/incomingCalls": [{"from": _ch_item("router", "pkg/api.py")}],
        }
    )
    triples = _triples(client)
    # caller --calls--> me
    assert any(
        t.predicate == "calls"
        and t.subject == "pkg/api.py:router"
        and t.object == "pkg/mod.py:handler"
        for t in triples
    )


def test_outgoing_calls_become_calls_edges() -> None:
    client = FakeClient(
        {
            "textDocument/prepareCallHierarchy": [_ch_item("handler", "pkg/mod.py")],
            "callHierarchy/outgoingCalls": [{"to": _ch_item("db_query", "pkg/db.py")}],
        }
    )
    triples = _triples(client)
    assert any(
        t.predicate == "calls"
        and t.subject == "pkg/mod.py:handler"
        and t.object == "pkg/db.py:db_query"
        for t in triples
    )


def test_type_hierarchy_supertypes() -> None:
    client = FakeClient(
        {
            "textDocument/prepareTypeHierarchy": [_ch_item("Handler", "pkg/mod.py")],
            "typeHierarchy/supertypes": [
                {"name": "BaseHandler", "uri": "file://pkg/base.py", "kind": 5},
                {"name": "Runnable", "uri": "file://pkg/iface.py", "kind": 11},
            ],
        }
    )
    triples = extract_cross_refs(
        client,
        file_path="pkg/mod.py",
        symbol_name="Handler",
        line=10,
        character=4,
        source_chunk_id="c1",
    )
    # class (kind 5) -> extends ; interface (kind 11) -> implements
    assert any(
        t.predicate == "extends" and t.object == "pkg/base.py:BaseHandler"
        for t in triples
    )
    assert any(
        t.predicate == "implements" and t.object == "pkg/iface.py:Runnable"
        for t in triples
    )


def test_empty_responses_yield_no_triples() -> None:
    assert _triples(FakeClient({})) == []


def test_client_exception_is_swallowed() -> None:
    class Boom:
        def request(self, method, params=None):
            raise RuntimeError("server died")

    assert _triples(Boom()) == []
