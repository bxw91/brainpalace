"""Decide whether a config save would invalidate/strand already-indexed data.

Pure logic: the route fetches the project server's /index/fingerprint and the
changed dotpaths, then asks this module whether to block and how to describe the
conflict. No I/O here.
"""

from __future__ import annotations

from typing import Any

# Edited dotpaths that make existing indexed data incompatible:
# - embedding.provider/model: invalidate stored vectors (a dimension change is a
#   downstream consequence, surfaced by the fingerprint, not edited directly).
# - storage.backend / graphrag.store_type: move data to a different store,
#   stranding what is already indexed.
BREAKING_DOTPATHS: set[str] = {
    "embedding.provider",
    "embedding.model",
    "storage.backend",
    "graphrag.store_type",
}


def breaking_changes(changed: set[str]) -> set[str]:
    """The subset of changed dotpaths that are data-incompatible."""
    return changed & BREAKING_DOTPATHS


def _leaf(data: dict[str, Any], dotpath: str) -> Any:
    node: Any = data
    for part in dotpath.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def build_conflict(
    breaking: set[str],
    merged: dict[str, Any],
    existing: dict[str, Any],
    fingerprint: dict[str, Any],
) -> dict[str, Any]:
    """Structured 409 payload describing the data-incompatible change."""
    fields = [
        {
            "dotpath": dp,
            "current": _leaf(existing, dp),
            "new": _leaf(merged, dp),
        }
        for dp in sorted(breaking)
    ]
    return {
        "conflict": "data_incompatible",
        "message": (
            "This change is incompatible with already-indexed data. Empty the "
            "databases or reindex before saving."
        ),
        "fields": fields,
        "counts": {
            "documents": fingerprint.get("doc_count"),
            "chunks": fingerprint.get("chunk_count"),
        },
    }
