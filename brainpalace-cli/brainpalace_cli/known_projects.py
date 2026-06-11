"""Durable store of every BrainPalace project ever started on this machine.

The running registry (``registry.json``) only lists *currently running*
servers — stopping a server deregisters it. To keep a project listable and
Start-able after it stops (and across reboots), every ``brainpalace start``
records the project here, at ``<XDG_STATE>/brainpalace/known_projects.json``.

This is the single source of truth for "projects ever started", shared by the
CLI, the dashboard fleet list, and the uninstall teardown. Reads go through
:func:`load_existing`, which prunes projects whose directory no longer exists
on disk — a deleted project disappears from every list automatically.

Shape on disk::

    {
      "/abs/project/root": {"state_dir": "/abs/.brainpalace", "project_name": "root"},
      ...
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brainpalace_cli.xdg_paths import get_xdg_state_dir

KNOWN_FILE = "known_projects.json"


def _path() -> Path:
    return get_xdg_state_dir() / KNOWN_FILE


def _load_raw() -> dict[str, dict[str, Any]]:
    path = _path()
    if not path.exists():
        return {}
    try:
        data: dict[str, dict[str, Any]] = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(known: dict[str, dict[str, Any]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(known, indent=2))


def remember(
    project_root: str | Path, state_dir: str | Path, project_name: str
) -> None:
    """Record (or refresh) a project in the durable known-projects store."""
    root = str(Path(project_root).resolve())
    entry = {"state_dir": str(state_dir), "project_name": project_name}
    known = _load_raw()
    if known.get(root) != entry:
        known[root] = entry
        _save(known)


def forget(project_root: str | Path) -> bool:
    """Drop a project from the store. Returns True if it was present."""
    root = str(Path(project_root).resolve())
    known = _load_raw()
    if root in known:
        del known[root]
        _save(known)
        return True
    return False


def prune_missing() -> list[str]:
    """Remove projects whose root directory no longer exists; persist if changed.

    Returns the list of pruned project roots.
    """
    known = _load_raw()
    removed = [root for root in known if not Path(root).is_dir()]
    if removed:
        for root in removed:
            del known[root]
        _save(known)
    return removed


def load_existing() -> dict[str, dict[str, Any]]:
    """Return the known projects whose directories still exist on disk.

    Prunes (and persists the removal of) any project whose root is gone, so
    every caller sees a self-healing list.
    """
    prune_missing()
    return _load_raw()
