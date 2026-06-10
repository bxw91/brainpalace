"""nodes_by_label + timeline_named store reads (dashboard plan 05)."""

from types import SimpleNamespace

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


def _node(nid: str, name: str, label: str):
    return SimpleNamespace(id=nid, name=name, label=label, properties={})


def _rel(src: str, label: str, tgt: str, props: dict | None = None):
    return SimpleNamespace(
        source_id=src, label=label, target_id=tgt, properties=props or {}
    )


def _seeded_store() -> SQLitePropertyGraphStore:
    store = SQLitePropertyGraphStore(":memory:")
    store.upsert_nodes(
        [
            _node("d1", "use poetry for packaging", "Decision"),
            _node("d2", "use uv for packaging", "Decision"),
            _node("f1", "pyproject.toml", "File"),
        ]
    )
    store.upsert_relations(
        [
            _rel("d1", "affects", "f1", {"valid_from": "2026-01-01T00:00:00"}),
            _rel("d2", "supersedes", "d1", {"valid_from": "2026-03-01T00:00:00"}),
        ]
    )
    return store


def test_nodes_by_label_filters_and_matches():
    store = _seeded_store()
    rows = store.nodes_by_label("Decision")
    assert {r["name"] for r in rows} == {
        "use poetry for packaging",
        "use uv for packaging",
    }
    rows = store.nodes_by_label("Decision", contains="poetry")
    assert [r["name"] for r in rows] == ["use poetry for packaging"]
    assert store.nodes_by_label("Nothing") == []


def test_nodes_by_label_limit_and_like_escaping():
    store = _seeded_store()
    assert store.nodes_by_label("Decision", limit=-1) == []
    assert [r["name"] for r in store.nodes_by_label("Decision", limit=1)] == [
        "use poetry for packaging"
    ]
    # "_" is a LIKE wildcard; escaped it must NOT match every name.
    assert store.nodes_by_label("Decision", contains="_") == []


def test_timeline_named_resolves_names_and_validity():
    store = _seeded_store()
    store.invalidate(
        "use poetry for packaging", "affects", "pyproject.toml", at="2026-03-01"
    )
    rows = store.timeline_named("use poetry for packaging")
    assert len(rows) == 2
    affects = next(r for r in rows if r["predicate"] == "affects")
    assert affects["subject"] == "use poetry for packaging"
    assert affects["object"] == "pyproject.toml"
    assert affects["valid"] is False
    supersedes = next(r for r in rows if r["predicate"] == "supersedes")
    assert supersedes["subject"] == "use uv for packaging"
    assert supersedes["valid"] is True


def test_timeline_named_unknown_entity_is_empty():
    store = _seeded_store()
    assert store.timeline_named("no such node") == []
