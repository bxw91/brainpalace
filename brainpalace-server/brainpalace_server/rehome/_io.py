# brainpalace_server/rehome/_io.py
"""Atomic JSON read/write for rehome state files (temp + os.replace)."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` as pretty JSON to ``path`` atomically.

    Writes to a temp file in the same directory, fsyncs, then ``os.replace``
    so a crash never leaves a half-written file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path) -> dict[str, Any]:
    """Read JSON from ``path``. Raises ``json.JSONDecodeError`` if corrupt."""
    result: dict[str, Any] = json.loads(Path(path).read_text())
    return result
