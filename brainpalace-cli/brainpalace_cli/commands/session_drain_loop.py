"""Loop-coordination layer for opt-in, window-safe queue draining.

`drain-tick` is the guarded single iteration for an explicit, user-launched loop
(e.g. `claude --model haiku` + `/loop 5m /brainpalace-drain`). It wraps the existing
`drain_queue()` with three safety mechanisms that stop a babysitter from silently
pinning the Claude Code 5-hour usage window or duplicating work:

- **mode gate** — only the free `subagent` engine ever loops.
- **atomic lock** — one live drainer per project (dedups parallel worktrees).
- **self-terminate** — `should_stop` after N consecutive empty drains.

All state lives under ``<project>/.brainpalace/``. No automatic trigger registers
this; it runs only when a user explicitly invokes it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

DEFAULT_EMPTY_STOP = 3
DEFAULT_LOCK_SLACK_SECONDS = 900  # a tick that hasn't refreshed in 15 min is dead

_LOCK = "drain-loop.lock"
_HEARTBEAT = "drain-loop.heartbeat"
_STREAK = "drain-loop.state"


def _pid_alive(pid: int) -> bool:
    """True if a process with ``pid`` exists on this host."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    return True


def _read_lock(path: Path) -> tuple[int, float] | None:
    try:
        parts = path.read_text().split()
        return int(parts[0]), float(parts[1])
    except (OSError, ValueError, IndexError):
        return None


def _lock_is_stale(path: Path, now: float, slack: int) -> bool:
    info = _read_lock(path)
    if info is None:
        return True
    pid, ts = info
    if not _pid_alive(pid):
        return True
    return (now - ts) > slack


def acquire_lock(state_dir: Path, *, now: float, pid: int, slack: int) -> bool:
    """Atomically claim the drain lock, reclaiming a stale one. Returns success."""
    path = state_dir / _LOCK
    body = f"{pid} {now}"
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if not _lock_is_stale(path, now, slack):
            return False
        try:
            path.unlink()
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except (OSError, FileExistsError):
            return False  # lost the reclaim race to another drainer
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    return True


def release_lock(state_dir: Path, *, pid: int) -> None:
    """Remove the lock iff we still own it (pid matches)."""
    path = state_dir / _LOCK
    info = _read_lock(path)
    if info is not None and info[0] == pid:
        try:
            path.unlink()
        except OSError:
            pass


def write_heartbeat(state_dir: Path, *, now: float) -> None:
    (state_dir / _HEARTBEAT).write_text(str(now), encoding="utf-8")


def read_heartbeat(state_dir: Path) -> float | None:
    try:
        return float((state_dir / _HEARTBEAT).read_text().strip())
    except (OSError, ValueError):
        return None


def read_streak(state_dir: Path) -> int:
    try:
        return max(0, int((state_dir / _STREAK).read_text().strip()))
    except (OSError, ValueError):
        return 0


def write_streak(state_dir: Path, value: int) -> None:
    (state_dir / _STREAK).write_text(str(max(0, value)), encoding="utf-8")


def resolve_empty_stop(project_root: Path) -> int:
    from .session_drain import _knob_int

    return max(
        1,
        _knob_int(
            "SESSION_DRAIN_EMPTY_STOP",
            "drain_loop_empty_stop",
            project_root,
            DEFAULT_EMPTY_STOP,
        ),
    )


def drain_tick(
    project_root: Path,
    *,
    empty_stop: int | None = None,
    now: float | None = None,
    pid: int | None = None,
    lock_slack: int = DEFAULT_LOCK_SLACK_SECONDS,
    mode: str | None = None,
    plugin_installed: bool | None = None,
) -> dict[str, Any]:
    """One guarded drain iteration. Returns a JSON-able summary dict.

    Keys: ``status`` (ok|skipped|locked), ``drained`` (ids), ``remaining`` (int),
    ``empty_streak`` (int), ``should_stop`` (bool — true after N empty drains, on a
    non-subagent mode, or when another drainer holds the lock).

    All side-effecting inputs (``now``, ``pid``, ``mode``, ``plugin_installed``) are
    injectable so the whole function is unit-testable without a live clock, process,
    or config file.
    """
    import time as _time

    from .backfill import read_extract_mode
    from .plugin_detect import claude_plugin_installed
    from .session_drain import drain_queue, resolve_budget, resolve_max_count

    now = _time.time() if now is None else now
    pid = os.getpid() if pid is None else pid
    stop_at = (
        resolve_empty_stop(project_root) if empty_stop is None else max(1, empty_stop)
    )

    resolved_mode = read_extract_mode(project_root) if mode is None else mode
    if resolved_mode == "auto":
        has_plugin = (
            claude_plugin_installed(project=project_root)
            if plugin_installed is None
            else plugin_installed
        )
        resolved_mode = "subagent" if has_plugin else "provider"
    if resolved_mode != "subagent":
        return {
            "status": "skipped",
            "drained": [],
            "remaining": 0,
            "empty_streak": 0,
            "should_stop": True,
        }

    state = project_root / ".brainpalace"
    state.mkdir(parents=True, exist_ok=True)

    if not acquire_lock(state, now=now, pid=pid, slack=lock_slack):
        return {
            "status": "locked",
            "drained": [],
            "remaining": 0,
            "empty_streak": read_streak(state),
            "should_stop": True,
        }
    try:
        write_heartbeat(state, now=now)
        res = drain_queue(
            project_root,
            budget=resolve_budget(project_root),
            cap=resolve_max_count(project_root),
            cooldown=0,  # the loop interval is the pacing; cooldown is for the hook
            now=now,
        )
        streak = 0 if res["drained"] else read_streak(state) + 1
        write_streak(state, streak)
        return {
            "status": "ok",
            "drained": res["drained"],
            "remaining": res["remaining"],
            "empty_streak": streak,
            "should_stop": streak >= stop_at,
        }
    finally:
        release_lock(state, pid=pid)


import json as _json  # noqa: E402

import click  # noqa: E402

from ..discovery import discover_project_dir  # noqa: E402


@click.command("drain-tick")
@click.option(
    "--project",
    "-p",
    type=click.Path(file_okay=False),
    default=None,
    help="Project root (default: discover .brainpalace/ from cwd).",
)
@click.option(
    "--empty-stop",
    type=int,
    default=None,
    help="Self-terminate after N consecutive empty drains (default 3).",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def drain_tick_command(
    project: str | None, empty_stop: int | None, json_output: bool
) -> None:
    """One guarded drain iteration for an OPT-IN summarization loop.

    Mode-gated (subagent engine only), single-drainer locked, and self-terminating
    after N empty drains. Intended for `/loop 5m /brainpalace-drain` in a dedicated
    `claude --model haiku` session; safe to run by hand. Never auto-runs."""
    root = Path(project).resolve() if project else discover_project_dir(Path.cwd())
    if root is None:
        res: dict[str, Any] = {
            "status": "no-project",
            "drained": [],
            "remaining": 0,
            "empty_streak": 0,
            "should_stop": True,
        }
        if json_output:
            click.echo(_json.dumps(res))
        return
    res = drain_tick(root, empty_stop=empty_stop)
    if json_output:
        click.echo(_json.dumps(res))
    elif res["drained"]:
        click.echo(" ".join(res["drained"]))
