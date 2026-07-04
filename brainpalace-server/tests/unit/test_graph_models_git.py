"""Plan C Task 1 — git entity kinds + predicates in the graph schema."""

from brainpalace_server.models.graph import (
    ENTITY_TYPES,
    GIT_ENTITY_TYPES,
    RELATIONSHIP_TYPES,
    normalize_entity_type,
)


def test_git_entity_types_registered() -> None:
    assert GIT_ENTITY_TYPES == ["Commit", "Author"]
    assert "Commit" in ENTITY_TYPES
    assert "Author" in ENTITY_TYPES


def test_git_predicates_registered() -> None:
    assert "modifies" in RELATIONSHIP_TYPES
    assert "authored_by" in RELATIONSHIP_TYPES


def test_normalization_covers_git_kinds() -> None:
    assert normalize_entity_type("commit") == "Commit"
    assert normalize_entity_type("AUTHOR") == "Author"
