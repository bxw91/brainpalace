from brainpalace_dashboard.services.data_guard import (
    BREAKING_DOTPATHS,
    breaking_changes,
    build_conflict,
    drop_effective_noops,
    drop_global_noops,
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


def test_drop_effective_noops_drops_materialized_inherited_default():
    # The reported bug: embedding.* go null -> their already-effective default.
    breaking = {"embedding.provider", "embedding.model"}
    merged = {"embedding": {"provider": "openai", "model": "text-embedding-3-large"}}
    effective = {
        "embedding.provider": {"value": "openai", "source": "default"},
        "embedding.model": {"value": "text-embedding-3-large", "source": "default"},
    }
    assert drop_effective_noops(breaking, merged, effective) == set()


def test_drop_effective_noops_keeps_real_change():
    breaking = {"embedding.model"}
    merged = {"embedding": {"model": "text-embedding-3-small"}}
    effective = {
        "embedding.model": {"value": "text-embedding-3-large", "source": "default"}
    }
    assert drop_effective_noops(breaking, merged, effective) == {"embedding.model"}


def test_drop_global_noops_shielded_by_project_override():
    # Saving global embedding=openai, but the instance pins it at project level.
    breaking = {"embedding.provider"}
    global_values = {"embedding": {"provider": "openai"}}
    inst_eff = {"embedding.provider": {"value": "cohere", "source": "project"}}
    assert drop_global_noops(breaking, global_values, inst_eff) == set()


def test_drop_global_noops_same_effective_value():
    breaking = {"embedding.provider"}
    global_values = {"embedding": {"provider": "openai"}}
    inst_eff = {"embedding.provider": {"value": "openai", "source": "default"}}
    assert drop_global_noops(breaking, global_values, inst_eff) == set()


def test_drop_global_noops_real_inherited_change():
    breaking = {"embedding.provider"}
    global_values = {"embedding": {"provider": "cohere"}}
    inst_eff = {"embedding.provider": {"value": "openai", "source": "default"}}
    assert drop_global_noops(breaking, global_values, inst_eff) == {
        "embedding.provider"
    }


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
