"""Rehome the project config's absolute exclude paths (spec D6).

Reads the PROJECT config.yaml verbatim (never the merged global<project view, so
inherited globals are never materialized into the sparse project file), swaps
in-root absolute ``indexing.exclude_patterns`` entries, and writes back only when
something changed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from brainpalace_server.rehome.swap import swap_exclude_patterns


def rehome_project_excludes(state_dir: Path, old_root: str, new_root: str) -> int:
    cfg_path = Path(state_dir) / "config.yaml"
    if not cfg_path.exists():
        return 0
    data = yaml.safe_load(cfg_path.read_text()) or {}
    indexing = data.get("indexing")
    if not isinstance(indexing, dict):
        return 0
    patterns = indexing.get("exclude_patterns")
    if not isinstance(patterns, list):
        return 0
    swapped = swap_exclude_patterns([str(p) for p in patterns], old_root, new_root)
    changed = sum(1 for a, b in zip(patterns, swapped) if a != b)
    if not changed:
        return 0
    indexing["exclude_patterns"] = swapped
    tmp = cfg_path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False))
    tmp.replace(cfg_path)
    return changed
