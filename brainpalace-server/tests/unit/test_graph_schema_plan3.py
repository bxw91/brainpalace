from brainpalace_server.models.graph import (
    CODE_ENTITY_TYPES,
    ENTITY_TYPES,
    RELATIONSHIP_TYPES,
    normalize_entity_type,
)


def test_new_predicates_registered():
    assert "decorated_by" in RELATIONSHIP_TYPES
    assert "handled_by" in RELATIONSHIP_TYPES


def test_new_code_entity_kinds():
    for kind in ("File", "Folder", "Decorator"):
        assert kind in CODE_ENTITY_TYPES
        assert kind in ENTITY_TYPES


def test_entity_types_have_no_duplicates():
    assert len(ENTITY_TYPES) == len(set(ENTITY_TYPES))


def test_normalize_new_kinds():
    assert normalize_entity_type("folder") == "Folder"
    assert normalize_entity_type("decorator") == "Decorator"
    assert normalize_entity_type("file") == "File"
