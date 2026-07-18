"""Detect and reap orphan BrainPalace server processes.

An orphan is a running ``brainpalace_server.api.main`` uvicorn whose PID is not
referenced by any live entry in the global registry (registry.json), AND whose
parent is not itself a live, registry-referenced server (D5 — a millisecond-wide
false positive during a healthy server's own ``subprocess`` call). These leak
when a server is started from a different install surface (source venv vs pipx)
or when a runtime.json is overwritten, and they hold ports so auto_port climbs.

A genuine orphan may be a deadlocked fork clone that inherited (but never
released) the listening socket — it cannot run its own SIGTERM handler, so
``reap_orphans`` escalates: SIGTERM, poll for real death, SIGKILL any survivor,
then re-probes. ``ReapOutcome.survived`` is the honest list of PIDs that refused
to die even under SIGKILL (permission, uninterruptible sleep, …) — callers must
surface this, never silently claim a false "reaped".
"""

from __future__ import annotations

import glob
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass

_SERVER_MARKER = "brainpalace_server.api.main"

#: Grace window for a SIGTERM'd orphan to exit before escalating to SIGKILL,
#: and the poll interval while waiting (D2). Mirrors update._STOP_GRACE_SECS /
#: _STOP_POLL_SECS (5.0/0.25) — 3s is enough for a healthy stray server to
#: close its socket, short enough that `stop --all` stays interactive.
_REAP_GRACE_SECS = 3.0
_REAP_POLL_SECS = 0.25


@dataclass(frozen=True)
class ReapOutcome:
    """Result of a reap pass — the one fact every caller needs (D3)."""

    reaped: list[int]  # confirmed dead (SIGTERM or SIGKILL)
    survived: list[int]  # still alive after SIGKILL


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


def parent_pid(pid: int) -> int | None:
    """``pid``'s PPid from ``/proc``, or ``None`` if it can't be determined (D5)."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


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


def find_orphan_pids(
    running: list[int],
    referenced: set[int],
    *,
    ppid_fn: Callable[[int], int | None] = parent_pid,
) -> list[int]:
    """Running server PIDs not referenced by a live registry entry.

    A PID whose parent is itself a live, registry-referenced server is
    excluded (D5): during a healthy server's own ``subprocess`` call there is
    a millisecond window where a forked child matches the cmdline marker;
    killing it would break the parent's spawn. A genuine orphan is always
    reparented (PPid 1 or a subreaper), never a live tracked server.
    """
    orphans = []
    for pid in running:
        if pid in referenced:
            continue
        ppid = ppid_fn(pid)
        if ppid is not None and ppid in referenced:
            continue
        orphans.append(pid)
    return orphans


def reap_orphans(
    *,
    grace: float = _REAP_GRACE_SECS,
    poll: float = _REAP_POLL_SECS,
    kill_fn: Callable[[int, int], None] | None = None,
    list_server_pids_fn: Callable[[], list[int]] = list_server_pids,
    registry_loader: Callable[[], dict[str, object]] | None = None,
    alive_fn: Callable[[int], bool] = is_process_alive,
    ppid_fn: Callable[[int], int | None] = parent_pid,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ReapOutcome:
    """SIGTERM every orphan, escalate to SIGKILL, and report only confirmed death.

    D1: an orphan has no owner to wait on it, and the dominant real-world case
    (a deadlocked fork clone) cannot answer SIGTERM at all — so the reaper
    itself must poll for real death and escalate, exactly like
    ``update._stop_all_instances`` / ``InstanceService.stop`` already do.

    ``kill_fn``/``registry_loader``/``sleep_fn`` are injectable for tests;
    defaults send real signals, read the real registry, and really sleep.
    """
    if kill_fn is None:

        def kill_fn(pid: int, sig: int) -> None:
            os.kill(pid, sig)

    if registry_loader is None:
        from brainpalace_cli.commands.list_cmd import get_registry

        registry_loader = get_registry

    running = list_server_pids_fn()
    refd = referenced_pids(registry_loader(), alive_fn=alive_fn)
    orphans = find_orphan_pids(running, refd, ppid_fn=ppid_fn)

    for pid in orphans:
        try:
            kill_fn(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            continue

    deadline = time.monotonic() + grace
    remaining = [p for p in orphans if alive_fn(p)]
    while remaining and time.monotonic() < deadline:
        sleep_fn(poll)
        remaining = [p for p in remaining if alive_fn(p)]

    for pid in remaining:
        try:
            kill_fn(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            continue

    if remaining:
        sleep_fn(poll)

    survived = [p for p in remaining if alive_fn(p)]
    reaped = [p for p in orphans if p not in survived]

    return ReapOutcome(reaped=reaped, survived=survived)
