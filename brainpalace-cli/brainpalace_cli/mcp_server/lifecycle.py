"""``--ensure-server`` lifecycle hook for the MCP shim.

Hardens problem 1 from the Phase Q plan: non-Claude-Code clients have
no start hook, so without this every MCP tool call returns "no server
running" until the user manually runs ``brainpalace start``. When the
``--ensure-server`` flag is passed to ``brainpalace mcp``, this module
starts the HTTP server for the spawn-time CWD project before the stdio
loop opens.

Constraints (Phase Q risk register):

* **Spawn-time CWD project only.** Does NOT start servers for
  ``path``-targeted projects on individual tool calls.
* **Never auto-``init``.** If ``.brainpalace/`` is absent the project is
  uninitialised and is left alone — the explicit failure is preferable
  to silently scaffolding a server with default providers.
* **Server outlives the MCP shim.** ``subprocess.Popen`` with
  ``start_new_session=True`` produces a detached daemon, identical to
  what ``brainpalace start`` would have created. Other clients (Claude
  Code, additional MCP clients) can share it.
* **Concurrent boot race.** Two ``--ensure-server`` MCP clients booting
  at once both call here; the live-runtime check at the top of
  :func:`_start_for` makes the second one detect the first's server.
* **Start failure must not hang the MCP handshake.** :func:`ensure_http_server`
  is a top-level ``try/except`` — anything that goes wrong is logged to
  stderr and swallowed. The stdio loop opens afterwards regardless;
  tool calls then return the normal "server not running" error.

stdout silence is essential: the MCP transport owns the parent process's
stdout pipe, so any ``print`` here would corrupt the JSON-RPC framing.
Every diagnostic in this module writes to ``sys.stderr``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from brainpalace_cli.commands.start import (
    check_health,
    cleanup_stale,
    find_available_port,
    is_process_alive,
    read_bind,
    read_runtime,
    update_registry,
    write_runtime,
)
from brainpalace_cli.discovery import discover_project_dir, discover_server_url
from brainpalace_cli.migration import resolve_state_dir_with_fallback
from brainpalace_cli.xdg_paths import migrate_legacy_paths


def ensure_http_server(start: Path | None = None, timeout: int = 60) -> None:
    """Start the BrainPalace HTTP server for the project at ``start`` if none is live.

    ``start`` defaults to the current working directory — i.e. the
    spawn-time CWD of the MCP shim. ``timeout`` is the maximum number
    of seconds to wait for the newly-spawned server to pass its
    ``/health/`` check before giving up.

    Behaviour summary (no-ops are silent):

    * project not initialised → return
    * a healthy server already running → return
    * otherwise, spawn a detached uvicorn, write ``runtime.json``,
      update the global registry, wait for ``/health/`` → 200

    Any exception is caught and logged to stderr — this function
    **never raises** so the MCP handshake cannot hang on it.
    """
    try:
        project = discover_project_dir(start)
        if project is None:
            return  # uninitialised; tools will return a clear error
        if discover_server_url(start) is not None:
            return  # already healthy
        _start_for(project, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — must not hang the MCP handshake
        print(f"brainpalace mcp: --ensure-server failed: {exc}", file=sys.stderr)


def _start_for(project_root: Path, timeout: int) -> None:
    """Spawn a detached uvicorn server for ``project_root`` and wait for ``/health/``.

    Mirrors the daemonising branch of ``start_command`` in
    ``brainpalace_cli.commands.start`` but is invoked programmatically
    and writes no rich panels / no stdout (stdout belongs to the MCP
    transport in the parent process).
    """
    migrate_legacy_paths()
    state_dir = resolve_state_dir_with_fallback(project_root)
    if not state_dir.exists():
        # Project initialised flag is the existence of the state dir.
        return

    # Race-safe: another --ensure-server may have just started one.
    runtime = read_runtime(state_dir)
    if runtime:
        pid = runtime.get("pid", 0)
        base_url = runtime.get("base_url", "")
        if pid and is_process_alive(pid) and base_url and check_health(base_url):
            return
        cleanup_stale(state_dir)

    config = read_bind(state_dir)
    bind_host: str = config.get("bind_host", "127.0.0.1")
    port: int
    if config.get("auto_port", True):
        start_port = int(config.get("port_range_start", 8000))
        end_port = int(config.get("port_range_end", 8100))
        available = find_available_port(bind_host, start_port, end_port)
        if available is None:
            raise RuntimeError(f"no available port in range {start_port}-{end_port}")
        port = available
    else:
        port = int(config.get("port", 8000))

    base_url = f"http://{bind_host}:{port}"
    from brainpalace_cli.commands.start import build_server_command

    server_cmd = build_server_command(bind_host, port)
    env = os.environ.copy()
    env["BRAINPALACE_PROJECT_ROOT"] = str(project_root)
    env["BRAINPALACE_STATE_DIR"] = str(state_dir)

    log_dir = state_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / "server.log"
    stderr_log = log_dir / "server.err"

    with open(stdout_log, "a") as so, open(stderr_log, "a") as se:
        proc = subprocess.Popen(
            server_cmd,
            env=env,
            stdout=so,
            stderr=se,
            start_new_session=True,
        )

    runtime_state: dict[str, Any] = {
        "schema_version": "1.0",
        "mode": "project",
        "project_root": str(project_root),
        "instance_id": uuid4().hex[:12],
        "base_url": base_url,
        "bind_host": bind_host,
        "port": port,
        "pid": proc.pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_runtime(state_dir, runtime_state)
    update_registry(project_root, state_dir)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if check_health(base_url, timeout=2.0):
            return
        if proc.poll() is not None:
            raise RuntimeError(
                f"server exited before becoming healthy (see {stderr_log})"
            )
        time.sleep(0.5)
    raise RuntimeError(f"server did not become healthy within {timeout}s")
