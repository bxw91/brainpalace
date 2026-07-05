import pytest

from brainpalace_cli.doc_sync.mode_meta import MODE_META, resolve_meta

ALL_MODES = [
    "vector",
    "bm25",
    "hybrid",
    "graph",
    "multi",
    "compute",
    "scan",
    "absence",
    "timeline",
]


def test_mode_meta_covers_all_live_modes():
    assert set(MODE_META) == set(ALL_MODES)


def test_resolve_meta_preserves_given_order():
    pairs = resolve_meta(["graph", "vector"])
    assert [m for m, _ in pairs] == ["graph", "vector"]
    assert pairs[0][1] is MODE_META["graph"]


def test_resolve_meta_raises_on_missing_mode():
    with pytest.raises(ValueError, match="ghost"):
        resolve_meta(["vector", "ghost"])
