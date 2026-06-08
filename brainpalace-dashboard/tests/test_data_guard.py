from brainpalace_dashboard.services.data_guard import (
    BREAKING_DOTPATHS,
    breaking_changes,
    build_conflict,
)


def test_breaking_set_contents():
    assert BREAKING_DOTPATHS == {
        "embedding.provider",
        "embedding.model",
        "storage.backend",
        "graphrag.store_type",
    }


def test_breaking_changes_filters_to_breaking_only():
    changed = {"embedding.model", "reranker.enabled", "graphrag.store_type"}
    assert breaking_changes(changed) == {"embedding.model", "graphrag.store_type"}


def test_build_conflict_has_fields_and_counts():
    merged = {"embedding": {"model": "text-embedding-3-small"}}
    existing = {"embedding": {"model": "text-embedding-3-large"}}
    fingerprint = {"has_data": True, "doc_count": 736, "chunk_count": 6658}
    conflict = build_conflict({"embedding.model"}, merged, existing, fingerprint)
    assert conflict["conflict"] == "data_incompatible"
    assert conflict["counts"] == {"documents": 736, "chunks": 6658}
    field = next(f for f in conflict["fields"] if f["dotpath"] == "embedding.model")
    assert field["current"] == "text-embedding-3-large"
    assert field["new"] == "text-embedding-3-small"
