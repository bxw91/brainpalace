"""Tests for SQLitePropertyGraphStore (Phase 090).

The store duck-types the llama_index PropertyGraphStore surface the rest of the
codebase consumes (``get`` / ``get_triplets`` / ``upsert_nodes`` /
``upsert_relations`` / ``persist`` / ``from_persist_path`` / ``clear``) backed by
a plain ``sqlite3`` database, plus a temporal-validity model
(``valid_from`` / ``valid_until`` / ``invalidate`` / ``timeline`` / ``as_of``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore

try:
    from llama_index.core.graph_stores.types import EntityNode, Relation
except ImportError:  # pragma: no cover - llama_index always present in CI
    EntityNode = Relation = None  # type: ignore


def _node(name: str, label: str = "Entity") -> EntityNode:
    return EntityNode(name=name, label=label)


def _rel(subj: str, label: str, obj: str, **props) -> Relation:
    s, o = _node(subj), _node(obj)
    return Relation(label=label, source_id=s.id, target_id=o.id, properties=props)


@pytest.fixture
def store() -> SQLitePropertyGraphStore:
    return SQLitePropertyGraphStore(":memory:")


def _add(store: SQLitePropertyGraphStore, subj, label, obj, **props):
    s, o = _node(subj), _node(obj)
    store.upsert_nodes([s, o])
    store.upsert_relations(
        [Relation(label=label, source_id=s.id, target_id=o.id, properties=props)]
    )


class TestDuckInterface:
    def test_upsert_and_get_nodes(self, store) -> None:
        store.upsert_nodes([_node("parse_config", "Function")])
        names = {n.name for n in store.get()}
        assert "parse_config" in names

    def test_node_upsert_is_idempotent(self, store) -> None:
        store.upsert_nodes([_node("foo"), _node("foo")])
        store.upsert_nodes([_node("foo")])
        assert sum(1 for n in store.get() if n.name == "foo") == 1

    def test_get_triplets_returns_property_graph_tuples(self, store) -> None:
        _add(store, "parse_config", "calls", "load_yaml", source_chunk_id="c1")
        triplets = store.get_triplets(entity_names=["parse_config"])
        assert len(triplets) == 1
        subj, rel, obj = triplets[0]
        assert subj.name == "parse_config"
        assert rel.label == "calls"
        assert obj.name == "load_yaml"
        assert rel.properties.get("source_chunk_id") == "c1"

    def test_get_triplets_matches_object_endpoint(self, store) -> None:
        _add(store, "a", "rel", "b")
        assert len(store.get_triplets(entity_names=["b"])) == 1

    def test_get_triplets_empty_for_unknown_entity(self, store) -> None:
        _add(store, "a", "rel", "b")
        assert store.get_triplets(entity_names=["zzz"]) == []

    def test_relation_upsert_dedups_on_endpoints_and_label(self, store) -> None:
        _add(store, "a", "rel", "b")
        _add(store, "a", "rel", "b")
        assert len(store.get_triplets(entity_names=["a"])) == 1

    def test_clear_empties_store(self, store) -> None:
        _add(store, "a", "rel", "b")
        store.clear()
        assert store.get() == []
        assert store.get_triplets(entity_names=["a"]) == []

    def test_node_label_preserved(self, store) -> None:
        store.upsert_nodes([_node("Foo", "Decision")])
        node = next(n for n in store.get() if n.name == "Foo")
        assert node.label == "Decision"


class TestPersistence:
    def test_triplet_survives_reopen(self, tmp_path: Path) -> None:
        db = tmp_path / "graph.db"
        s1 = SQLitePropertyGraphStore(str(db))
        _add(s1, "a", "rel", "b")
        s1.persist()
        s2 = SQLitePropertyGraphStore.from_persist_path(str(db))
        assert len(s2.get_triplets(entity_names=["a"])) == 1

    def test_writes_are_incremental(self, tmp_path: Path) -> None:
        """A second add does not rewrite/lose the first (no whole-file dump)."""
        db = tmp_path / "graph.db"
        s = SQLitePropertyGraphStore(str(db))
        _add(s, "a", "rel", "b")
        _add(s, "c", "rel", "d")
        s.persist()
        s2 = SQLitePropertyGraphStore.from_persist_path(str(db))
        assert len(s2.get()) == 4


class TestTemporalValidity:
    def test_new_edge_is_currently_valid(self, store) -> None:
        _add(store, "a", "rel", "b")
        assert len(store.get_triplets(entity_names=["a"])) == 1

    def test_invalidate_excludes_from_default_query(self, store) -> None:
        _add(store, "a", "supersedes", "b")
        n = store.invalidate("a", "supersedes", "b")
        assert n == 1
        assert store.get_triplets(entity_names=["a"]) == []

    def test_as_of_time_travel(self, store) -> None:
        _add(store, "a", "rel", "b")
        mid = datetime.now(timezone.utc)  # after add, before invalidation
        store.invalidate("a", "rel", "b", at=mid + timedelta(seconds=1))
        # currently (now > invalidation) -> excluded
        assert store.get_triplets(entity_names=["a"]) == []
        # as-of a moment when it was still open -> included
        assert len(store.get_triplets(entity_names=["a"], as_of=mid)) == 1
        # as-of before it ever existed -> excluded
        early = datetime.now(timezone.utc) - timedelta(days=1)
        assert store.get_triplets(entity_names=["a"], as_of=early) == []

    def test_include_invalid_returns_invalidated_edges(self, store) -> None:
        _add(store, "a", "rel", "b")
        store.invalidate("a", "rel", "b")
        assert len(store.get_triplets(entity_names=["a"], include_invalid=True)) == 1

    def test_timeline_orders_entity_edges(self, store) -> None:
        _add(store, "d1", "supersedes", "d0")
        _add(store, "d2", "supersedes", "d1")
        store.invalidate("d1", "supersedes", "d0")
        tl = store.timeline("d1")
        assert len(tl) == 2
        # each entry carries validity info
        assert all("valid_from" in e for e in tl)


class TestCounts:
    def test_counts_reflect_store(self, store) -> None:
        _add(store, "a", "rel", "b")
        _add(store, "b", "rel", "c")
        assert store.node_count() == 3
        assert store.edge_count() == 2

    def test_edge_count_excludes_invalidated_by_default(self, store) -> None:
        _add(store, "a", "rel", "b")
        store.invalidate("a", "rel", "b")
        assert store.edge_count() == 0
        assert store.edge_count(include_invalid=True) == 1


class TestBrowserSeeds:
    def test_top_nodes_ranks_by_active_degree(self, store) -> None:
        # hub touches 3 edges; leaf touches 1.
        _add(store, "hub", "rel", "a")
        _add(store, "hub", "rel", "b")
        _add(store, "hub", "rel", "c")
        _add(store, "leaf", "rel", "z")
        top = store.top_nodes(limit=10)
        assert top[0]["name"] == "hub"
        assert top[0]["degree"] == 3
        assert "leaf" in [n["name"] for n in top]

    def test_top_nodes_omits_isolated_and_invalidated(self, store) -> None:
        # An isolated node (no edges) and a node whose only edge is invalidated
        # must not appear — they make a useless starting point.
        store.upsert_nodes([_node("lonely")])
        _add(store, "x", "rel", "y")
        store.invalidate("x", "rel", "y")
        assert store.top_nodes(limit=10) == []
