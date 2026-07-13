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


def _path(state_dir: Path) -> Path:
    return Path(state_dir) / IDENTITY_FILENAME


def load_identity(state_dir: Path) -> ProjectIdentity | None:
    p = _path(state_dir)
    if not p.exists():
        return None
    try:
        data = read_json(p)
        return ProjectIdentity(
            project_uuid=data["project_uuid"], indexed_root=data["indexed_root"]
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
