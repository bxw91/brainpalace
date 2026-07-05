"""Phase 4 Task 1 — CO-2 substrate proof + supersession coverage guard.

CO-2 is DECIDED as (a) the edge-only rule: no node-level validity columns are
added because the edge-validity machinery already exists AND is populated.
This test proves the exact substrate `timeline` mode reads — over a real
SQLitePropertyGraphStore — so the decision rests on verified behaviour, not a
claim. Seeding mirrors tests/test_graph_store_browse_reads.py.
"""

from __future__ import annotations

from types import SimpleNamespace

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


def _node(nid: str, name: str, label: str) -> SimpleNamespace:
    return SimpleNamespace(id=nid, name=name, label=label, properties={})


def _rel(src: str, label: str, tgt: str, props: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        source_id=src, label=label, target_id=tgt, properties=props or {}
    )


def _seeded() -> SQLitePropertyGraphStore:
    """A superseded decision + its stale fact + the superseding decision."""
    store = SQLitePropertyGraphStore(":memory:")
    store.upsert_nodes(
        [
            _node("d1", "use in-memory cache", "Decision"),
            _node("d2", "use Redis cache", "Decision"),
            _node("f1", "cache.py", "File"),
        ]
    )
    store.upsert_relations(
        [
            _rel("d1", "touches", "f1", {"valid_from": "2026-01-01T00:00:00"}),
            _rel("d2", "superseded-by", "d1", {"valid_from": "2026-03-01T00:00:00"}),
        ]
    )
    return store


def test_timeline_reconstructs_full_ordered_history() -> None:
    """The whole belief chain is walkable: stale fact closed, history preserved,
    ordered by valid_from. This is exactly what _execute_timeline_query wraps."""
    store = _seeded()
    # supersession closes the stale fact (what session_linker does)...
    store.invalidate("use in-memory cache", "touches", "cache.py", at="2026-03-01")

    rows = store.timeline_named("use in-memory cache")
    # both edges surface (full history, invalid included) ordered by valid_from
    assert [r["predicate"] for r in rows] == ["touches", "superseded-by"]

    touches = next(r for r in rows if r["predicate"] == "touches")
    assert touches["valid"] is False  # stale fact is closed
    assert touches["valid_until"] is not None

    history = next(r for r in rows if r["predicate"] == "superseded-by")
    assert history["valid"] is True  # the belief-chain edge is preserved


def test_edge_validity_transition_without_supersedes() -> None:
    """A plain re-index closure (invalidate_by_source_file style) yields a
    validity transition with NO superseded-by predicate — the coverage
    distinction for non-decision entities documented in docs/TIMELINE.md."""
    store = _seeded()
    store.invalidate("use in-memory cache", "touches", "cache.py", at="2026-02-01")
    rows = store.timeline_named("cache.py")
    assert [r["predicate"] for r in rows] == ["touches"]
    assert rows[0]["valid"] is False
    assert all(r["predicate"] != "superseded-by" for r in rows)


def test_search_nodes_resolves_the_named_entity() -> None:
    """The entity resolver timeline mode uses: case-insensitive substring on
    node name, best node first."""
    store = _seeded()
    hits = store.search_nodes("cache.py", limit=1)
    assert hits and hits[0]["name"] == "cache.py"
    # case-insensitive (compiler lowercases the entity)
    assert store.search_nodes("REDIS", limit=1)[0]["name"] == "use Redis cache"
    # a phrase matching no node → empty (falls back to hybrid at runtime)
    assert store.search_nodes("nonexistent entity", limit=1) == []


def test_unknown_entity_timeline_is_empty() -> None:
    assert _seeded().timeline_named("no such node") == []
