"""Server-side entity typing for session triplets (Phase 100).

The session triplet wire schema (frozen in Phase 020) carries only
``{subject, relation, object, evidence_turn}`` — no entity types. Rather than
churn the schema or the extractor prompts, we derive node types deterministically
from the (closed-vocabulary) relation, using its documented direction
(subject → object). Ambiguous endpoints are left untyped (``None`` → the graph
store's ``"Entity"`` label) so we never guess.

The directions mirror the 070 command / 080 subagent prompts, which are the
source of truth for the vocabulary.
"""

from __future__ import annotations

# relation -> (subject_type, object_type); None = leave untyped (don't guess).
RELATION_ENTITY_TYPES: dict[str, tuple[str | None, str | None]] = {
    # edited/created file -> the thing it implements (free-text concept)
    "touches": ("File", None),
    # error/bug -> the fix/decision that resolves it
    "fixed-by": ("Error", "Decision"),
    # older decision -> the newer decision that replaces it
    "superseded-by": ("Decision", "Decision"),
    # tool/command -> the session it ran in
    "ran-in": ("Tool", "Session"),
    # task/phase -> its prerequisite task/phase
    "depends-on": ("Task", "Task"),
    # actor/session -> a decision it made
    "decided": ("Session", "Decision"),
}


def types_for(relation: str) -> tuple[str | None, str | None]:
    """Return ``(subject_type, object_type)`` for a session relation.

    Unknown relations (should not occur — the payload is vocab-validated
    before it reaches here) return ``(None, None)``.
    """
    return RELATION_ENTITY_TYPES.get(relation, (None, None))
