"""Plan E — reverse dependency closure (impact analysis)."""

from brainpalace_server.storage.sqlite_graph_store import (
    IMPACT_PREDICATES,
    SQLitePropertyGraphStore,
)

# tests/storage is not a package (no __init__.py) — keep helpers local.


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


def _store():
    # handler calls helper; api.py imports lib.py; helper defined_in lib.py.
    s = SQLitePropertyGraphStore(":memory:")
    s.upsert_nodes(
        [
            _N("lib.py", "lib.py", "File"),
            _N("api.py", "api.py", "File"),
            _N("lib.py:helper", "helper", "Function"),
            _N("api.py:handler", "handler", "Function"),
            _N("gc", "deadbeef touch lib", "Commit", domain="git"),
        ]
    )
    s.upsert_relations(
        [
            _R("api.py:handler", "lib.py:helper", "calls"),
            _R("api.py", "lib.py", "imports"),
            _R("lib.py:helper", "lib.py", "defined_in"),
            _R("gc", "lib.py", "modifies"),  # NOT an impact predicate
        ]
    )
    return s


def test_direct_dependents_at_depth_one():
    s = _store()
    out = s.impact("lib.py:helper", max_depth=1)
    assert [(r["id"], r["depth"], r["via_predicate"]) for r in out] == [
        ("api.py:handler", 1, "calls")
    ]


def test_transitive_closure_orders_by_depth():
    s = _store()
    out = s.impact("lib.py", max_depth=3)
    by_id = {r["id"]: r for r in out}
    # api.py imports lib.py (d1); helper defined_in lib.py (d1);
    # handler calls helper (d2). The git commit edge is excluded.
    assert by_id["api.py"]["depth"] == 1
    assert by_id["lib.py:helper"]["depth"] == 1
    assert by_id["api.py:handler"]["depth"] == 2
    assert "gc" not in by_id
    assert [r["depth"] for r in out] == sorted(r["depth"] for r in out)


def test_predicates_filter():
    s = _store()
    out = s.impact("lib.py", max_depth=3, predicates=["imports"])
    assert [r["id"] for r in out] == ["api.py"]


def test_limit_truncates():
    s = _store()
    assert len(s.impact("lib.py", max_depth=3, limit=1)) == 1


def test_unknown_node_and_default_predicates():
    s = _store()
    assert s.impact("zzz") == []
    assert "calls" in IMPACT_PREDICATES and "modifies" not in IMPACT_PREDICATES


def test_invalidated_edges_excluded():
    s = _store()
    s.invalidate("handler", "calls", "helper")
    assert s.impact("lib.py:helper", max_depth=1) == []
