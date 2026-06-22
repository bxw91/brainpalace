"""Storage-backend ("db type") drift detection — main.check_storage_backend_drift.

The marker in the state dir records which backend the project's index data lives
under (backend-independent, because a switched-to backend is empty). A later start
on a different backend with no data → warn (data stranded under the old backend).
"""

from __future__ import annotations

import asyncio

from brainpalace_server.api.main import (
    _read_index_backend_marker,
    check_storage_backend_drift,
)


class _Backend:
    def __init__(self, count: int, initialized: bool = True):
        self._count = count
        self.is_initialized = initialized

    async def get_count(self) -> int:
        return self._count


def _run(coro):
    return asyncio.run(coro)


def test_records_backend_when_data_present(tmp_path):
    # Data under chroma → marker written, no warning.
    warn = _run(check_storage_backend_drift(tmp_path, "chroma", _Backend(count=42)))
    assert warn is None
    assert _read_index_backend_marker(tmp_path) == "chroma"


def test_warns_when_backend_changed_and_current_empty(tmp_path):
    # First start: data under chroma → marker = chroma.
    _run(check_storage_backend_drift(tmp_path, "chroma", _Backend(count=42)))
    # Config switched to postgres; the new store is empty → drift warning.
    warn = _run(check_storage_backend_drift(tmp_path, "postgres", _Backend(count=0)))
    assert warn is not None
    assert "chroma" in warn and "postgres" in warn
    # Marker is NOT overwritten — the data still lives under chroma.
    assert _read_index_backend_marker(tmp_path) == "chroma"


def test_fresh_project_no_marker_no_warning(tmp_path):
    warn = _run(check_storage_backend_drift(tmp_path, "postgres", _Backend(count=0)))
    assert warn is None
    assert _read_index_backend_marker(tmp_path) is None


def test_no_state_dir_is_noop():
    assert _run(check_storage_backend_drift(None, "chroma", _Backend(count=10))) is None


def test_switch_back_clears_warning(tmp_path):
    _run(check_storage_backend_drift(tmp_path, "chroma", _Backend(count=42)))
    # On postgres with no data → warns.
    assert _run(check_storage_backend_drift(tmp_path, "postgres", _Backend(count=0)))
    # Switch back to chroma where the data is → no warning, marker stays chroma.
    assert (
        _run(check_storage_backend_drift(tmp_path, "chroma", _Backend(count=42)))
        is None
    )
    assert _read_index_backend_marker(tmp_path) == "chroma"
