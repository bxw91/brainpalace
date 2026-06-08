"""Global running-server registry (`registry.json`) — the single writer.

Lives in the server package (not the CLI) so the *running server* can register
itself; the CLI imports these functions (dependency direction CLI -> server).
All mutations go through the locked read-modify-write here so concurrent writers
(multiple project servers, or a server racing the CLI) never lose an entry.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from brainpalace_server.locking import file_lock

logger = logging.getLogger(__name__)


def get_xdg_state_dir() -> Path:
    """`$XDG_STATE_HOME/brainpalace` (default `~/.local/state/brainpalace`)."""
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "brainpalace"


def registry_path() -> Path:
    """Path to the global `registry.json` (XDG state dir)."""
    return get_xdg_state_dir() / "registry.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        result: dict[str, Any] = json.loads(path.read_text())
        return result
    except Exception:  # noqa: BLE001 — corrupt file tolerated, matches CLI
        return {}


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def upsert_entry(project_root: Path, state_dir: Path) -> None:
    """Add/refresh this project's registry entry under an exclusive lock."""
    try:
        path = registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path.with_suffix(".json.lock")):
            data = _load(path)
            data[str(project_root)] = {
                "state_dir": str(state_dir),
                "project_name": Path(project_root).name,
            }
            _atomic_write(path, data)
    except Exception as exc:  # noqa: BLE001 — never raise into callers
        logger.warning("registry upsert failed for %s: %s", project_root, exc)


def remove_entry(project_root: Path) -> None:
    """Drop this project's registry entry (no-op if absent) under the lock."""
    try:
        path = registry_path()
        if not path.exists():
            return
        with file_lock(path.with_suffix(".json.lock")):
            data = _load(path)
            if str(project_root) in data:
                del data[str(project_root)]
                _atomic_write(path, data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("registry remove failed for %s: %s", project_root, exc)
