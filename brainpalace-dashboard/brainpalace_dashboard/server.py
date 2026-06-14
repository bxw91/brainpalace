"""Dashboard self-lifecycle: launch / stop / status.

The dashboard manages its own process, separate from per-project BrainPalace
servers. It keeps a dedicated runtime pidfile (``dashboard.json``) under the XDG
state dir so ``stop``/``status`` can find a backgrounded process. This is
deliberately NOT the project-server ``registry.json``.

Mirrors the runtime read/write/delete + health-check + port-scan patterns from
``brainpalace_cli.commands.start``.
"""

from __future__ import annotations

import glob
import json
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from brainpalace_cli.xdg_paths import get_xdg_state_dir

from brainpalace_dashboard.config import load_dashboard_config

#: Filename of the dashboard's own runtime pidfile under the XDG state dir.
RUNTIME_FILE = "dashboard.json"

#: Port scan range for the dashboard process.
PORT_SCAN_START = 8787
PORT_SCAN_END = 8887

#: cmdline marker identifying a dashboard uvicorn process (the app factory
#: target). Used to find orphans by process scan — the pidfile tracks only one.
DASHBOARD_MARKER = "brainpalace_dashboard.app"


def _dashboard_runtime_path() -> Path:
    """Path to the dashboard runtime pidfile (``<XDG_STATE>/dashboard.json``)."""
    return Path(get_xdg_state_dir()) / RUNTIME_FILE


def read_dashboard_runtime() -> dict[str, Any] | None:
    """Return the parsed dashboard runtime, or ``None`` if absent/corrupt."""
    path = _dashboard_runtime_path()
    if not path.exists():
        return None
    try:
        result: dict[str, Any] = json.loads(path.read_text())
        return result
    except Exception:
        return None


def write_dashboard_runtime(runtime: dict[str, Any]) -> None:
    """Persist the dashboard runtime pidfile, creating the state dir if needed."""
    path = _dashboard_runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runtime, indent=2))


def delete_dashboard_runtime() -> None:
    """Remove the dashboard runtime pidfile if it exists."""
    path = _dashboard_runtime_path()
    if path.exists():
        path.unlink()


def _proc_state(pid: int) -> str | None:
    """Single-char process state from ``/proc/<pid>/stat`` (Linux), else None.

    ``comm`` (field 2) may itself contain spaces and parentheses, so we slice
    after the *last* ``)`` before reading the state field.
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read()
    except OSError:
        return None
    try:
        after = data[data.rindex(b")") + 1 :].split()
    except ValueError:
        return None
    return after[0].decode("ascii", "replace") if after else None


def _is_alive(pid: int) -> bool:
    """Return True if ``pid`` exists and is not a zombie.

    A zombie (a child that exited but was never ``wait()``ed for) still answers
    ``os.kill(pid, 0)`` as alive. The dashboard is spawned by a long-lived
    project server that may not reap it, so without the zombie check a corpse
    would poison the singleton pidfile forever — ``dashboard_status`` would keep
    reporting "running" and self-heal would never relaunch. Treat ``Z``/``X`` as
    not-alive; fall back to the kill-probe where ``/proc`` is unavailable.
    """
    if _proc_state(pid) in ("Z", "X", "x"):
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _proc_state_dir(pid: int) -> Path | None:
    """Resolve the XDG state dir a process is using, from ``/proc/<pid>/environ``.

    Mirrors ``get_xdg_state_dir`` against the target's own environment so reaping
    can be scoped to dashboards that share *our* state dir. Returns None when the
    environment is unreadable (caller treats unknowns as out-of-scope so a test
    running under a tmp ``XDG_STATE_HOME`` never SIGTERMs the developer's real
    dashboard, and vice-versa).
    """
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            raw = f.read()
    except OSError:
        return None
    env: dict[str, str] = {}
    for item in raw.split(b"\x00"):
        if b"=" in item:
            key, _, val = item.partition(b"=")
            env[key.decode("utf-8", "replace")] = val.decode("utf-8", "replace")
    xdg = env.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "brainpalace"
    home = env.get("HOME")
    if home:
        return Path(home) / ".local" / "state" / "brainpalace"
    return None


def list_dashboard_pids() -> list[int]:
    """Running dashboard uvicorn PIDs that share *our* XDG state dir.

    The pidfile tracks a single dashboard, but a lost/overwritten pidfile plus
    the climbing port scan can leave earlier dashboards running and untracked.
    Scanning the process table is the only surface-agnostic way to find them
    (pipx vs source venv share the same XDG state, but a stale pidfile hides
    the strays).

    Reaping is **scoped to the active state dir**: a dashboard whose
    ``XDG_STATE_HOME`` resolves elsewhere (e.g. a pytest run under a tmp state
    dir) belongs to a different fleet and must not be SIGTERMed — that
    cross-context reaping is exactly how a test run used to kill the developer's
    real dashboard. Returns an empty list off Linux (no ``/proc``).
    """
    target = get_xdg_state_dir().resolve()
    pids: list[int] = []
    for cmdline_path in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(cmdline_path, "rb") as f:
                cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if DASHBOARD_MARKER not in cmd:
            continue
        try:
            pid = int(cmdline_path.split("/")[2])
        except (IndexError, ValueError):
            continue
        state_dir = _proc_state_dir(pid)
        if state_dir is None or state_dir.resolve() != target:
            continue  # unknown or foreign state dir -> not ours to reap
        pids.append(pid)
    return pids


def reap_orphan_dashboards(
    keep_pid: int | None = None,
    *,
    kill_fn: Callable[[int], None] | None = None,
    list_fn: Callable[[], list[int]] | None = None,
) -> list[int]:
    """SIGTERM every dashboard process except ``keep_pid``; return reaped PIDs.

    The dashboard is a singleton, so any dashboard process other than the one
    being kept is an orphan. ``kill_fn``/``list_fn`` are injectable for tests;
    defaults send SIGTERM and scan ``/proc`` (resolved at call time so the scan
    stays monkeypatchable).
    """
    if kill_fn is None:

        def kill_fn(pid: int) -> None:
            os.kill(pid, signal.SIGTERM)

    if list_fn is None:
        list_fn = list_dashboard_pids

    reaped: list[int] = []
    for pid in list_fn():
        if pid == keep_pid or pid == os.getpid():
            continue
        try:
            kill_fn(pid)
        except (OSError, ProcessLookupError):
            continue
        reaped.append(pid)
    return reaped


def _port_free(host: str, port: int) -> bool:
    """Return True if ``host:port`` can be bound (i.e. is free)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_free_port(
    host: str, start: int = PORT_SCAN_START, end: int = PORT_SCAN_END
) -> int | None:
    """Find the first free port in ``[start, end]`` on ``host``, else ``None``."""
    for port in range(start, end + 1):
        if _port_free(host, port):
            return port
    return None


def _wait_port_free(
    host: str, port: int, pids: list[int], *, timeout: float = 5.0
) -> bool:
    """Wait until ``host:port`` frees up; escalate reaped ``pids`` to SIGKILL.

    Used right after reaping our own dashboards so a restart reclaims the
    configured port instead of letting the scan climb. A reaped process still
    holding the port past the halfway mark is hard-killed. Returns True when the
    port is free.
    """
    deadline = time.monotonic() + timeout
    escalated = False
    while time.monotonic() < deadline:
        if _port_free(host, port):
            return True
        # Past halfway, hard-kill any reaped process that won't let go.
        if not escalated and time.monotonic() >= deadline - timeout / 2:
            for pid in pids:
                if _is_alive(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        pass
            escalated = True
        time.sleep(0.1)
    return _port_free(host, port)


def _wait_healthy(url: str, timeout: int = 20) -> bool:
    """Poll the dashboard health endpoint derived from a ``/dashboard/`` URL.

    Args:
        url: The dashboard base URL (``http://host:port/dashboard/``).
        timeout: Max seconds to wait.

    Returns:
        True once ``/dashboard/api/health`` responds 200, else False on timeout.
    """
    base = url.rstrip("/")
    if base.endswith("/dashboard"):
        base = base[: -len("/dashboard")]
    health_url = f"{base}/dashboard/api/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = Request(health_url, method="GET")
            with urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _base_url(host: str, port: int) -> str:
    """Build the dashboard base URL for ``host:port``."""
    return f"http://{host}:{port}/dashboard/"


def launch_dashboard(
    host: str | None = None,
    port: int | None = None,
    *,
    open_browser: bool = True,
    foreground: bool = False,
    timeout: int = 20,
) -> str:
    """Launch the dashboard process and return its base URL.

    Scans for a free port starting at ``port`` (or the configured/default
    8787), spawns uvicorn against the app factory, writes the runtime pidfile,
    waits for health, and optionally opens a browser.

    Args:
        host: Bind host; falls back to config (default ``127.0.0.1``).
        port: Preferred port; falls back to config (default ``8787``). The scan
            starts here and walks up to ``PORT_SCAN_END``.
        open_browser: Open the dashboard in a browser once healthy.
        foreground: Run uvicorn in the foreground (blocks); no browser opened.
        timeout: Seconds to wait for health before raising.

    Returns:
        The dashboard base URL (``http://host:port/dashboard/``).

    Raises:
        RuntimeError: If a dashboard is already running, no free port is found,
            or the process never becomes healthy.
    """
    existing = read_dashboard_runtime()
    if existing and _is_alive(int(existing.get("pid", -1))):
        # Tracked dashboard is healthy — reap any *other* dashboards (strays
        # left on climbed ports by an earlier lost pidfile) and refuse to spawn.
        reap_orphan_dashboards(keep_pid=int(existing["pid"]))
        raise RuntimeError(
            f"Dashboard already running (pid {existing['pid']}) at "
            f"{existing.get('base_url')}"
        )

    # No healthy tracked dashboard. Reap any orphaned dashboards (lost pidfile /
    # climbed-port duplicates) so the scan below reclaims the base port instead
    # of stacking yet another instance on top of the survivors.
    reaped = reap_orphan_dashboards(keep_pid=None)

    cfg = load_dashboard_config()
    host = host or cfg.host
    start_port = port or cfg.port

    # A just-reaped dashboard can still hold the configured port for a moment
    # (SIGTERM in flight / socket teardown). Without waiting, the scan below
    # would climb to the next port and the dashboard would silently drift off
    # its configured port (e.g. 8787 → 8789) on every restart. Wait for the
    # port to free — escalating a stubborn reaped process to SIGKILL — so a
    # restart always reclaims the configured default.
    if reaped and not _port_free(host, start_port):
        _wait_port_free(host, start_port, reaped, timeout=5.0)

    # Scan from the requested/configured port upward.
    chosen: int | None = None
    for candidate in range(start_port, PORT_SCAN_END + 1):
        if _port_free(host, candidate):
            chosen = candidate
            break
    if chosen is None:
        raise RuntimeError(
            f"No free port in range {start_port}-{PORT_SCAN_END} on {host}"
        )

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "brainpalace_dashboard.app:create_app",
        "--factory",
        "--host",
        host,
        "--port",
        str(chosen),
    ]
    url = _base_url(host, chosen)

    if foreground:
        # Block on uvicorn; do not write a backgrounded runtime/pidfile.
        subprocess.run(cmd, check=False)
        return url

    # Daemonize: detach into a new session and redirect output to a log file so
    # the spawning terminal is freed (no inherited tty / process group) — mirrors
    # how `brainpalace start` backgrounds a project server.
    state_dir = get_xdg_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / "dashboard.log"
    # Detach into a new session in production so the spawning terminal is freed.
    # Under pytest, DON'T detach: a real daemon spawned by a test must not
    # outlive the test process tree (orphaned to init, surviving forever on a
    # climbed port reading the tmp state dir was the dashboard-leak bug).
    detach = not os.environ.get("PYTEST_CURRENT_TEST")
    with open(log_path, "a") as log_f:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=detach,
        )
    write_dashboard_runtime(
        {
            "pid": process.pid,
            "host": host,
            "port": chosen,
            "base_url": url,
            "log_file": str(log_path),
        }
    )

    if not _wait_healthy(url, timeout=timeout):
        raise RuntimeError(
            f"Dashboard did not become healthy within {timeout}s (pid "
            f"{process.pid}); check for errors and try again."
        )

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    return url


def ensure_running(
    *, open_browser_if_new: bool = False, timeout: int = 20
) -> dict[str, Any]:
    """Idempotently ensure the singleton dashboard is up; return its state.

    If a healthy dashboard is already running, return it untouched (no relaunch,
    no browser). Otherwise launch it (port-scan, health-wait) and — only on this
    fresh-launch path — open a browser when ``open_browser_if_new`` is set.

    Args:
        open_browser_if_new: Open a browser only when the dashboard is launched
            here (never when one was already running).
        timeout: Seconds to wait for a freshly launched dashboard to go healthy.

    Returns:
        ``{"status": "running", "base_url", "port", "started": bool,
        "healthy": bool}``. ``started`` is True only when launched by this call.

    Raises:
        RuntimeError: If a launch was attempted and failed (no free port / never
            healthy / lost a start race). Callers that must not fail should wrap
            this in a try/except.
    """
    status = dashboard_status()
    if status.get("status") == "running" and status.get("healthy"):
        return {**status, "started": False}

    if status.get("status") == "running":
        # Tracked but unhealthy (dead socket / hung worker): the pidfile is
        # poisoned. Clear it so launch_dashboard doesn't see a "live" tracked
        # dashboard and refuse — then relaunch a working one.
        delete_dashboard_runtime()

    url = launch_dashboard(
        open_browser=open_browser_if_new, foreground=False, timeout=timeout
    )
    runtime = read_dashboard_runtime() or {}
    return {
        "status": "running",
        "base_url": url,
        "port": runtime.get("port"),
        "started": True,
        "healthy": True,
    }


def stop_dashboard(timeout: float = 10.0) -> dict[str, Any]:
    """Stop the running dashboard process via SIGTERM and clear the runtime.

    Args:
        timeout: Seconds to wait for the process to exit before giving up.

    Returns:
        A dict with ``status`` one of ``stopped`` / ``not_running``, plus the
        ``pid`` when one was signalled.
    """
    runtime = read_dashboard_runtime()
    pid = int(runtime.get("pid", -1)) if runtime else -1

    stopped_pid: int | None = None
    if pid > 0:
        try:
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not _is_alive(pid):
                    break
                time.sleep(0.2)
            stopped_pid = pid
        except ProcessLookupError:
            pass

    # The dashboard is a singleton — "stop" means leave none running. Reap any
    # other dashboard processes (climbed-port orphans, or strays from a lost
    # pidfile) the tracked pid didn't cover.
    reaped = [p for p in reap_orphan_dashboards(keep_pid=None) if p != stopped_pid]
    delete_dashboard_runtime()

    if stopped_pid is None and not reaped:
        return {"status": "not_running"}
    result: dict[str, Any] = {"status": "stopped"}
    if stopped_pid is not None:
        result["pid"] = stopped_pid
    if reaped:
        result["reaped"] = reaped
    return result


def dashboard_status() -> dict[str, Any]:
    """Report the dashboard's current state.

    Returns:
        A dict describing the dashboard: ``status`` (``running`` /
        ``not_running``), and when running also ``pid``, ``port``,
        ``base_url``, and ``healthy``.
    """
    runtime = read_dashboard_runtime()
    if not runtime:
        return {"status": "not_running"}

    pid = int(runtime.get("pid", -1))
    if pid <= 0 or not _is_alive(pid):
        return {"status": "not_running", "stale": True}

    base_url = str(runtime.get("base_url", ""))
    healthy = _wait_healthy(base_url, timeout=2) if base_url else False
    return {
        "status": "running",
        "pid": pid,
        "port": runtime.get("port"),
        "base_url": base_url,
        "healthy": healthy,
    }
