"""Detect and reap orphan BrainPalace server processes.

An orphan is a running ``brainpalace_server.api.main`` uvicorn whose PID is not
referenced by any live entry in the global registry (registry.json). These leak
when a server is started from a different install surface (source venv vs pipx)
or when a runtime.json is overwritten, and they hold ports so auto_port climbs.
"""

from __future__ import annotations

import glob
import os
import signal
from collections.abc import Callable

_SERVER_MARKER = "brainpalace_server.api.main"


def is_process_alive(pid: int) -> bool:
    """Whether ``pid`` names a live process (signal 0 probe)."""
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def list_server_pids() -> list[int]:
    """All running BrainPalace *RAG server* PIDs (excludes the dashboard)."""
    pids: list[int] = []
    for cmdline_path in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(cmdline_path, "rb") as f:
                cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if _SERVER_MARKER in cmd:
            try:
                pids.append(int(cmdline_path.split("/")[2]))
            except (IndexError, ValueError):
                continue
    return pids


def referenced_pids(
    registry: dict[str, object], *, alive_fn: Callable[[int], bool] = is_process_alive
) -> set[int]:
    """PIDs the registry references that are actually alive."""
    out: set[int] = set()
    for entry in registry.values():
        pid = entry.get("pid") if isinstance(entry, dict) else None
        if isinstance(pid, int) and pid > 0 and alive_fn(pid):
            out.add(pid)
    return out


def find_orphan_pids(running: list[int], referenced: set[int]) -> list[int]:
    """Running server PIDs not referenced by a live registry entry."""
    return [p for p in running if p not in referenced]


def reap_orphans(
    *,
    kill_fn: Callable[[int], None] | None = None,
    list_server_pids_fn: Callable[[], list[int]] = list_server_pids,
    registry_loader: Callable[[], dict[str, object]] | None = None,
    alive_fn: Callable[[int], bool] = is_process_alive,
) -> list[int]:
    """Kill every server PID not referenced by a live registry entry.

    Returns the list of reaped PIDs. ``kill_fn``/``registry_loader`` are
    injectable for tests; defaults send SIGTERM and read the real registry.
    """
    if kill_fn is None:

        def kill_fn(pid: int) -> None:
            os.kill(pid, signal.SIGTERM)

    if registry_loader is None:
        from brainpalace_cli.commands.list_cmd import get_registry

        registry_loader = get_registry

    running = list_server_pids_fn()
    refd = referenced_pids(registry_loader(), alive_fn=alive_fn)
    orphans = find_orphan_pids(running, refd)
    for pid in orphans:
        try:
            kill_fn(pid)
        except (OSError, ProcessLookupError):
            continue
    return orphans
