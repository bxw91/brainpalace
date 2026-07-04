"""Plan E — store-backed entity match + weight-aware graph ranking."""

from unittest.mock import patch

from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.graph_store import GraphStoreManager
from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


class _N:
    def __init__(self, id, name, label="Entity", domain="code"):
        self.id = id
        self.name = name
        self.label = label
        self.properties = {}
        self.domain = domain


class _R:
    def __init__(self, source_id, target_id, label):
        self.source_id = source_id
        self.target_id = target_id
        self.label = label
        self.properties = {}


def _index_manager(tmp_path):
    store = SQLitePropertyGraphStore(str(tmp_path / "g.db"))
    mgr = GraphStoreManager(tmp_path, store_type="sqlite")
    mgr._graph_store = store
    mgr._initialized = True
    gim = GraphIndexManager(graph_store=mgr)
    return store, gim


def test_matching_uses_search_nodes_not_full_scan(tmp_path):
    store, gim = _index_manager(tmp_path)
    store.upsert_nodes(
        [_N("a", "invoice_total", "Function"), _N("b", "billing.py", "File")]
    )
    store.upsert_relations([_R("a", "b", "defined_in")])
    with (
        patch("brainpalace_server.indexing.graph_index.settings") as s,
        patch.object(store, "get", side_effect=AssertionError("full scan used")),
    ):
        s.ENABLE_GRAPH_INDEX = True
        results = gim.query("invoice_total")
    assert results
    assert results[0]["predicate"] == "defined_in"


def test_weight_property_becomes_graph_score_and_orders(tmp_path):
    store, gim = _index_manager(tmp_path)
    store.upsert_nodes(
        [
            _N("x", "target_fn", "Function"),
            _N("h", "heavy.py", "File"),
            _N("l", "light.py", "File"),
        ]
    )

    class _WR(_R):
        def __init__(self, source_id, target_id, label, weight):
            super().__init__(source_id, target_id, label)
            self.properties = {"weight": weight, "source_chunk_id": source_id}

    store.upsert_relations(
        [
            _WR("h", "x", "references", 0.9),
            _WR("l", "x", "references", 0.2),
        ]
    )
    with patch("brainpalace_server.indexing.graph_index.settings") as s:
        s.ENABLE_GRAPH_INDEX = True
        results = gim.query("target_fn")
    scores = [r["graph_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 0.9 and 0.2 in scores


def test_missing_weight_defaults_to_one(tmp_path):
    store, gim = _index_manager(tmp_path)
    store.upsert_nodes([_N("a", "plain_fn", "Function"), _N("b", "f.py", "File")])
    store.upsert_relations([_R("a", "b", "defined_in")])
    with patch("brainpalace_server.indexing.graph_index.settings") as s:
        s.ENABLE_GRAPH_INDEX = True
        results = gim.query("plain_fn")
    assert results[0]["graph_score"] == 1.0


def test_high_weight_edge_past_naive_cut_survives_truncation(tmp_path):
    """Regression: the per-entity truncation must sort matching triplets by
    weight (desc) BEFORE slicing to max_results — not truncate in raw
    discovery order, which would silently drop a high-weight edge past the
    cut in favor of earlier-discovered low-weight ones."""
    store, gim = _index_manager(tmp_path)
    store.upsert_nodes(
        [
            _N("x", "target_fn", "Function"),
            _N("a", "a.py", "File"),
            _N("b", "b.py", "File"),
            _N("c", "c.py", "File"),
        ]
    )

    class _WR(_R):
        def __init__(self, source_id, target_id, label, weight):
            super().__init__(source_id, target_id, label)
            self.properties = {"weight": weight, "source_chunk_id": source_id}

    # Discovery order (insertion order): low, low, HIGH — a naive
    # matching_triplets[:max_results] with max_results=2 would keep the two
    # low-weight edges and silently drop the high-weight one.
    store.upsert_relations(
        [
            _WR("a", "x", "references", 0.1),
            _WR("b", "x", "references", 0.2),
            _WR("c", "x", "references", 0.9),
        ]
    )
    with patch("brainpalace_server.indexing.graph_index.settings") as s:
        s.ENABLE_GRAPH_INDEX = True
        results = gim._find_entity_relationships("target_fn", depth=1, max_results=2)

    scores = sorted(r["graph_score"] for r in results)
    assert len(results) == 2
    assert 0.9 in scores  # highest-weight edge must survive the per-entity cut
    assert 0.1 not in scores  # lowest-weight edge is the one dropped
