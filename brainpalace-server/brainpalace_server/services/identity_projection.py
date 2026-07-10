"""G5 Task 9 (D2): one-way projection of identity ``person`` rows into the
knowledge graph as nodes, so relational traversal ("Mama's brother") works when
GraphRAG is enabled.

The projection is strictly one-directional: identity is user-asserted ground
truth living in its own store (D1) and is NEVER read back out of the graph.
With the graph disabled everything above still works unchanged — this is a
best-effort, guarded no-op in that case."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def project_person(graph_manager: Any, person: Any) -> bool:
    """Project a single ``Person`` into the graph as a node. Returns True when
    a node was written, False when the graph is off / unavailable (identity is
    unaffected either way). ``graph_manager`` is a ``GraphStoreManager`` (or
    None). Never raises — projection must not break an identity write."""
    if graph_manager is None or person is None:
        return False
    pid = getattr(person, "id", None)
    if not pid:
        return False
    try:
        return bool(
            graph_manager.upsert_person_node(
                pid,
                getattr(person, "name", None),
                kind=getattr(person, "kind", "person"),
                domain=getattr(person, "domain", "home"),
                sensitivity=getattr(person, "sensitivity", "normal"),
            )
        )
    except Exception as e:  # noqa: BLE001 — one-way projection is best-effort
        logger.warning("identity graph projection failed: %s", e)
        return False
