# brainpalace_server/rehome/state.py
"""Resumable rehome checkpoint file (spec D3 / schema)."""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from brainpalace_server.rehome._io import read_json, write_json_atomic

REHOME_FILENAME = "rehome.json"
RehomeStatus = Literal["pending", "in_progress", "done", "failed"]


class RehomeStateCorruptError(Exception):
    """rehome.json exists but cannot be parsed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RehomeState:
    project_uuid: str
    old_root: str
    new_root: str
    status: RehomeStatus
    phase: int
    cursor: str | None
    error: str | None
    started_at: str
    updated_at: str
    #: The new uuid minted ONCE at finalize (Part B, hardening #5). ``None``
    #: until finalize mints it; a resume that re-enters finalize reuses this
    #: persisted value instead of minting a second uuid (which would orphan the
    #: first and add a spurious lineage hop). Additive & defaulted so an older
    #: rehome.json without it loads as "not yet minted".
    minted_uuid: str | None = None


def new_rehome_state(project_uuid: str, old_root: str, new_root: str) -> RehomeState:
    ts = _now()
    return RehomeState(
        project_uuid=project_uuid,
        old_root=old_root,
        new_root=new_root,
        status="pending",
        phase=1,
        cursor=None,
        error=None,
        started_at=ts,
        updated_at=ts,
        minted_uuid=None,
    )


def _path(state_dir: Path) -> Path:
    return Path(state_dir) / "state" / REHOME_FILENAME


def _migrate_legacy_root_file(state_dir: Path) -> None:
    """C1/DC3: ``rehome.json`` used to live at ``state_dir`` root; move it into
    ``state/`` on first load so a pending/failed rehome checkpoint survives the
    C2 path change. Atomic (``os.replace``), one-time per project; no-op once
    migrated."""
    new_path = _path(state_dir)
    if new_path.exists():
        return
    old_path = Path(state_dir) / REHOME_FILENAME
    if old_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(old_path), str(new_path))


def load_rehome_state(state_dir: Path) -> RehomeState | None:
    _migrate_legacy_root_file(state_dir)
    p = _path(state_dir)
    if not p.exists():
        return None
    try:
        return RehomeState(**read_json(p))
    except (json.JSONDecodeError, TypeError) as e:
        raise RehomeStateCorruptError(str(p)) from e


def write_rehome_state(state_dir: Path, state: RehomeState) -> None:
    state.updated_at = _now()
    write_json_atomic(_path(state_dir), asdict(state))
