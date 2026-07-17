# brainpalace_server/rehome/identity.py
"""Durable per-project identity (spec D1 / A1). UUID, not path, is the identity."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from brainpalace_server.rehome._io import read_json, write_json_atomic

IDENTITY_FILENAME = "identity.json"


class IdentityCorruptError(Exception):
    """identity.json exists but cannot be parsed — refuse to guess a root."""


@dataclass
class ProjectIdentity:
    project_uuid: str
    indexed_root: str
    #: Lineage (Part B): the previous ``project_uuid`` / ``indexed_root`` this
    #: identity was forked from at rehome finalize. ``None`` when the project
    #: has never been rehomed (a first-seen / backfilled identity). A breadcrumb
    #: only — ``parent_index_root`` is a snapshot of where the parent was at fork
    #: time, never a live pointer to resolve-and-follow (DB3).
    parent_uuid: str | None = None
    parent_index_root: str | None = None


def _path(state_dir: Path) -> Path:
    return Path(state_dir) / "state" / IDENTITY_FILENAME


def _migrate_legacy_root_file(state_dir: Path) -> None:
    """C1/DC3: ``identity.json`` used to live at ``state_dir`` root; move it into
    ``state/`` on first load so existing projects keep their identity (and don't
    re-mint a fresh uuid, breaking Part B lineage) after the C2 path change.
    Atomic (``os.replace``), one-time per project; no-op once migrated."""
    new_path = _path(state_dir)
    if new_path.exists():
        return
    old_path = Path(state_dir) / IDENTITY_FILENAME
    if old_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(old_path), str(new_path))


def load_identity(state_dir: Path) -> ProjectIdentity | None:
    _migrate_legacy_root_file(state_dir)
    p = _path(state_dir)
    if not p.exists():
        return None
    try:
        data = read_json(p)
        # parent_* are additive (Part B): an older identity.json written before
        # lineage existed simply has no parent, so .get(...) -> None.
        return ProjectIdentity(
            project_uuid=data["project_uuid"],
            indexed_root=data["indexed_root"],
            parent_uuid=data.get("parent_uuid"),
            parent_index_root=data.get("parent_index_root"),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise IdentityCorruptError(str(p)) from e


def write_identity(state_dir: Path, identity: ProjectIdentity) -> None:
    write_json_atomic(_path(state_dir), asdict(identity))


def ensure_identity(state_dir: Path, current_root: Path) -> ProjectIdentity:
    """Return the existing identity, or backfill one adopting the current root (D7)."""
    existing = load_identity(state_dir)
    if existing is not None:
        return existing
    ident = ProjectIdentity(
        project_uuid=uuid4().hex, indexed_root=os.path.realpath(str(current_root))
    )
    write_identity(state_dir, ident)
    return ident
