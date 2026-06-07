"""Dashboard self-lifecycle: launch / stop / status.

The dashboard manages its own process, separate from per-project BrainPalace
servers. It keeps a dedicated runtime pidfile (``dashboard.json``) under the XDG
state dir so ``stop``/``status`` can find a backgrounded process. This is
deliberately NOT the project-server ``registry.json``.

Mirrors the runtime read/write/delete + health-check + port-scan patterns from
``brainpalace_cli.commands.start``.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
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


def _is_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` exists."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


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
        raise RuntimeError(
            f"Dashboard already running (pid {existing['pid']}) at "
            f"{existing.get('base_url')}"
        )

    cfg = load_dashboard_config()
    host = host or cfg.host
    start_port = port or cfg.port

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
    with open(log_path, "a") as log_f:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
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


def stop_dashboard(timeout: float = 10.0) -> dict[str, Any]:
    """Stop the running dashboard process via SIGTERM and clear the runtime.

    Args:
        timeout: Seconds to wait for the process to exit before giving up.

    Returns:
        A dict with ``status`` one of ``stopped`` / ``not_running``, plus the
        ``pid`` when one was signalled.
    """
    runtime = read_dashboard_runtime()
    if not runtime:
        return {"status": "not_running"}

    pid = int(runtime.get("pid", -1))
    if pid <= 0:
        delete_dashboard_runtime()
        return {"status": "not_running"}

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        delete_dashboard_runtime()
        return {"status": "not_running"}

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_alive(pid):
            break
        time.sleep(0.2)

    delete_dashboard_runtime()
    return {"status": "stopped", "pid": pid}


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
