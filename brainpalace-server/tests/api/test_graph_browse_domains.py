"""§3b — domains facet on the browse endpoints (default = unfiltered)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import graph as graph_router
from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture
def client(tmp_path, monkeypatch):
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    mgr.add_triplet(
        "a",
        "calls",
        "b",
        subject_id="f.py:a",
        object_id="f.py:b",
        subject_name="alpha",
        object_name="beta",
        source_file="f.py",
        domain="code",
    )
    mgr.add_triplet(
        "alpha decision",
        "references",
        "alpha doc",
        subject_id="doc:alpha-dec",
        object_id="doc:alpha-doc",
        subject_name="alpha decision",
        object_name="alpha doc",
        source_file="chunk_1",
        domain="doc",
    )
    monkeypatch.setattr(graph_router, "get_graph_store_manager", lambda: mgr)
    app = FastAPI()
    app.include_router(graph_router.router, prefix="/graph")
    return TestClient(app), mgr


def test_search_unfiltered_returns_both_domains(client):
    c, _ = client
    names = {n["name"] for n in c.get("/graph/nodes?q=alpha").json()["nodes"]}
    assert "alpha" in names
    assert "alpha decision" in names


def test_search_code_only_filters(client):
    c, _ = client
    body = c.get("/graph/nodes?q=alpha&domains=code").json()
    assert {n["name"] for n in body["nodes"]} == {"alpha"}
    assert all(n["domain"] == "code" for n in body["nodes"])


def test_top_nodes_respect_domains(client):
    c, _ = client
    body = c.get("/graph/top?domains=doc").json()
    assert body["nodes"]
    assert all(n["domain"] == "doc" for n in body["nodes"])


def test_neighbors_hide_cross_domain_edges(client):
    c, mgr = client
    # Link the code node to a doc node: edge shows only when BOTH domains on.
    mgr.add_triplet(
        "alpha doc",
        "references",
        "a",
        subject_id="doc:alpha-doc",
        object_id="f.py:a",
        subject_name="alpha doc",
        object_name="alpha",
        source_file="chunk_1",
        domain="doc",
    )
    # add_triplet stamps ONE domain on both endpoint nodes (grounded fact:
    # graph_store.py builds both _GNode's with the same `domain` arg), so the
    # upsert just flipped f.py:a to doc. Restore it — in production a code
    # node's domain is (re)asserted by its own domain's writes.
    mgr._graph_store._conn.execute("UPDATE nodes SET domain='code' WHERE id='f.py:a'")
    mgr._graph_store._conn.commit()
    code_only = c.get("/graph/neighbors?node=f.py:a&domains=code").json()
    labels = {e["label"] for e in code_only["edges"]}
    assert "calls" in labels  # same-domain edge stays
    assert "references" not in labels  # cross-domain edge hidden
    both = c.get("/graph/neighbors?node=f.py:a&domains=code,doc").json()
    assert any(e["label"] == "references" for e in both["edges"])


def test_unknown_domain_is_400(client):
    c, _ = client
    assert c.get("/graph/nodes?q=a&domains=bogus").status_code == 400
