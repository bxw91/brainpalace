"""G5 Task 9 (D2): one-way projection of person rows into the graph.

Graph OFF ⇒ projection is a no-op and identity is untouched. Graph ON ⇒ the
person appears as a graph node. Never a read-back — identity stays ground truth
in its own store (D1)."""

from __future__ import annotations

from brainpalace_server.config import settings
from brainpalace_server.services.identity_projection import project_person
from brainpalace_server.storage.graph_store import GraphStoreManager
from brainpalace_server.storage.identity_store import IdentityStore, Person


def _mgr(tmp_path):
    GraphStoreManager.reset_instance()
    mgr = GraphStoreManager(persist_dir=tmp_path / "graph", store_type="sqlite")
    mgr.initialize()
    return mgr


def test_projection_is_noop_when_graph_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", False)
    mgr = _mgr(tmp_path)
    store = IdentityStore(tmp_path / "identity.db")
    pid = store.upsert_person(Person(kind="person", domain="home", name="Ana"))

    assert project_person(mgr, store.get_person(pid)) is False
    # Identity is entirely unaffected by the graph being off.
    assert store.get_person(pid).name == "Ana"
    assert mgr.get_node(pid) is None


def test_person_appears_as_node_when_graph_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    mgr = _mgr(tmp_path)
    store = IdentityStore(tmp_path / "identity.db")
    pid = store.upsert_person(Person(kind="person", domain="home", name="Ana"))

    assert project_person(mgr, store.get_person(pid)) is True
    node = mgr.get_node(pid)
    assert node is not None
    assert node.get("name") == "Ana"
    # Projected under a label derived from the person kind.
    labels = {n["id"] for n in mgr.nodes_by_label("Person")}
    assert pid in labels


def test_unnamed_person_projects_with_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    mgr = _mgr(tmp_path)
    store = IdentityStore(tmp_path / "identity.db")
    pid = store.upsert_person(Person(kind="person", domain="home"))  # name NULL (D3)

    assert project_person(mgr, store.get_person(pid)) is True
    assert mgr.get_node(pid) is not None


def test_none_manager_is_safe(tmp_path):
    store = IdentityStore(tmp_path / "identity.db")
    pid = store.upsert_person(Person(kind="person", domain="home", name="Ana"))
    assert project_person(None, store.get_person(pid)) is False
