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


def drop_effective_noops(
    breaking: set[str],
    merged: dict[str, Any],
    effective: dict[str, dict[str, Any]],
) -> set[str]:
    """Keep only breaking dotpaths whose EFFECTIVE value actually changes.

    A key that was unset (inheriting global / code default) and is now written
    with the SAME value it already resolved to does not change the embedding /
    store identity — the index stays compatible. Materializing an inherited
    default (e.g. ``embedding.provider: null -> openai`` when openai was already
    effective) must therefore not be blocked. ``effective`` is the pre-save
    per-key ``{"value", "source"}`` map (``config_svc.effective``).
    """
    out: set[str] = set()
    for dp in breaking:
        eff = effective.get(dp)
        if eff is not None and eff.get("value") == _leaf(merged, dp):
            continue  # effective value unchanged → not a real break
        out.add(dp)
    return out


def drop_global_noops(
    breaking: set[str],
    global_values: dict[str, Any],
    instance_effective: dict[str, dict[str, Any]],
) -> set[str]:
    """Keep only breaking dotpaths whose change to GLOBAL alters THIS instance.

    A global save can strand an instance's index only when the instance actually
    inherits the key from global. So drop a dotpath when, for this instance:
    - it is overridden at the **project** layer (project wins → global is moot), or
    - the new global value equals the instance's current EFFECTIVE value (no-op).
    ``instance_effective`` is that instance's pre-save ``config_svc.effective``.
    """
    out: set[str] = set()
    for dp in breaking:
        eff = instance_effective.get(dp)
        if eff is not None and eff.get("source") == "project":
            continue  # project override shields it from a global change
        if eff is not None and eff.get("value") == _leaf(global_values, dp):
            continue  # same effective value → not a real break
        out.add(dp)
    return out


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
