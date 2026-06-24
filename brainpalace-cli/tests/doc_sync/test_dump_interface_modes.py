import json

from brainpalace_cli.doc_sync.introspect import dump_interface_json, live_snapshot


def test_snapshot_has_modes():
    snap = live_snapshot()
    assert set(snap.modes) == {"vector", "bm25", "hybrid", "graph", "multi", "compute"}


def test_dump_interface_emits_modes():
    data = json.loads(dump_interface_json())
    assert sorted(data["modes"]) == [
        "bm25",
        "compute",
        "graph",
        "hybrid",
        "multi",
        "vector",
    ]
