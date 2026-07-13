# brainpalace_server/rehome/detect.py
"""Move detection and component-wise prefix swapping (spec D1, D2, D8)."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class _HasIndexedRoot(Protocol):
    indexed_root: str


@dataclass
class MoveInfo:
    old_root: str
    new_root: str
    nested: bool


def _norm(p: str) -> str:
    return os.path.normcase(str(p).rstrip("/") or "/")


def _is_prefix(a: str, b: str) -> bool:
    """True if ``a`` is a component-wise path-prefix of ``b`` (or equal)."""
    a, b = _norm(a), _norm(b)
    return b == a or b.startswith(a.rstrip("/") + "/")


def prefix_swap(value: str, old_root: str, new_root: str) -> str:
    """Swap ``old_root`` -> ``new_root`` iff a component-wise prefix of ``value``."""
    if value == old_root:
        return new_root
    prefix = old_root.rstrip("/") + "/"
    if value.startswith(prefix):
        return new_root.rstrip("/") + "/" + value[len(prefix) :]
    return value


def detect_move(identity: _HasIndexedRoot, current_root: Path) -> MoveInfo | None:
    """Return a ``MoveInfo`` if the project moved since last index, else None.

    Compares realpaths. A case-only or symlink-only difference that resolves to
    the same inode is treated as no move.
    """
    old = os.path.realpath(identity.indexed_root)
    new = os.path.realpath(str(current_root))
    if _norm(old) == _norm(new):
        return None
    try:
        if os.path.exists(old) and os.path.samefile(old, new):
            return None
    except OSError:
        pass
    nested = _is_prefix(old, new) or _is_prefix(new, old)
    return MoveInfo(old_root=old, new_root=new, nested=nested)
