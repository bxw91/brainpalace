# tests/rehome/test_simple_graph_swap.py
"""Rehome the default `simple` (JSON) graph store: prefix-swap path-encoded node
ids / properties / relation endpoints, RECOMPUTING the composite relation keys +
triplets from the swapped parts (a naive leading swap would leave the target half
of `{source}_{label}_{target}` stale)."""

import json

from brainpalace_server.rehome.swap import rehome_simple_graph_json


def _sample():
    return {
        "nodes": {
            "/o/pkg/mod.py": {
                "label": "File",
                "properties": {"path": "/o/pkg/mod.py"},
                "name": "/o/pkg/mod.py",
            },
            "/o/pkg": {"label": "entity", "properties": {}, "name": "/o/pkg"},
            "/ext/x.py": {  # external — must be untouched
                "label": "File",
                "properties": {"path": "/ext/x.py"},
                "name": "/ext/x.py",
            },
        },
        "relations": {
            "/o/pkg_contains_/o/pkg/mod.py": {
                "label": "contains",
                "source_id": "/o/pkg",
                "target_id": "/o/pkg/mod.py",
                "properties": {"source_file": "/o/pkg/mod.py"},
            },
        },
        "triplets": [["/o/pkg", "contains", "/o/pkg/mod.py"]],
    }


def test_swaps_nodes_relations_triplets(tmp_path):
    p = tmp_path / "graph_store_llamaindex.json"
    p.write_text(json.dumps(_sample()))

    assert rehome_simple_graph_json(str(p), "/o", "/n") > 0

    data = json.loads(p.read_text())
    assert set(data["nodes"]) == {"/n/pkg/mod.py", "/n/pkg", "/ext/x.py"}
    assert data["nodes"]["/n/pkg/mod.py"]["properties"]["path"] == "/n/pkg/mod.py"
    assert data["nodes"]["/ext/x.py"]["properties"]["path"] == "/ext/x.py"

    # relation key RECOMPUTED from BOTH swapped endpoints (not leading-only)
    rel_key = next(iter(data["relations"]))
    assert rel_key == "/n/pkg_contains_/n/pkg/mod.py"
    rel = data["relations"][rel_key]
    assert rel["source_id"] == "/n/pkg"
    assert rel["target_id"] == "/n/pkg/mod.py"
    assert rel["properties"]["source_file"] == "/n/pkg/mod.py"

    assert data["triplets"] == [["/n/pkg", "contains", "/n/pkg/mod.py"]]


def test_noop_when_nothing_in_root(tmp_path):
    p = tmp_path / "graph_store_llamaindex.json"
    node = {"label": "File", "properties": {}, "name": "/ext/a.py"}
    original = json.dumps(
        {"nodes": {"/ext/a.py": node}, "relations": {}, "triplets": []}
    )
    p.write_text(original)
    assert rehome_simple_graph_json(str(p), "/o", "/n") == 0
    assert p.read_text() == original  # not rewritten


def test_missing_file(tmp_path):
    assert rehome_simple_graph_json(str(tmp_path / "nope.json"), "/o", "/n") == 0


def test_roundtrips_through_llamaindex(tmp_path):
    """After the swap the file must still load via SimplePropertyGraphStore."""
    from llama_index.core.graph_stores import SimplePropertyGraphStore
    from llama_index.core.graph_stores.types import EntityNode, Relation

    s = SimplePropertyGraphStore()
    s.upsert_nodes(
        [
            EntityNode(
                name="/o/pkg/mod.py",
                label="File",
                properties={"path": "/o/pkg/mod.py"},
            )
        ]
    )
    s.upsert_relations(
        [
            Relation(
                source_id="/o/pkg",
                target_id="/o/pkg/mod.py",
                label="contains",
                properties={"source_file": "/o/pkg/mod.py"},
            )
        ]
    )
    p = tmp_path / "graph_store_llamaindex.json"
    s.persist(str(p))

    assert rehome_simple_graph_json(str(p), "/o", "/n") > 0

    reloaded = SimplePropertyGraphStore.from_persist_path(str(p))
    names = {n.name for n in reloaded.get() if getattr(n, "name", None)}
    assert "/n/pkg/mod.py" in names
    assert not any(str(n).startswith("/o/") for n in names)
