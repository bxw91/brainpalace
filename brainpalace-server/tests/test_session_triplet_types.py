"""Relation → entity-type mapping for session triplets (Phase 100)."""

from __future__ import annotations

from brainpalace_server.models.graph import ENTITY_TYPES
from brainpalace_server.models.session_extract import Relation
from brainpalace_server.services.session_triplet_types import (
    RELATION_ENTITY_TYPES,
    types_for,
)

# the closed vocab as declared by the wire schema
VOCAB = set(Relation.__args__)  # type: ignore[attr-defined]


def test_mapping_covers_exactly_the_closed_vocab() -> None:
    assert set(RELATION_ENTITY_TYPES) == VOCAB


def test_documented_pairs() -> None:
    assert types_for("touches") == ("File", None)
    assert types_for("fixed-by") == ("Error", "Decision")
    assert types_for("superseded-by") == ("Decision", "Decision")
    assert types_for("ran-in") == ("Tool", "Session")
    assert types_for("depends-on") == ("Task", "Task")
    assert types_for("decided") == ("Session", "Decision")


def test_unknown_relation_is_untyped() -> None:
    assert types_for("not-a-relation") == (None, None)


def test_all_mapped_types_are_known_entity_types() -> None:
    for subj_t, obj_t in RELATION_ENTITY_TYPES.values():
        for t in (subj_t, obj_t):
            if t is not None:
                assert t in ENTITY_TYPES, f"{t} missing from ENTITY_TYPES"
