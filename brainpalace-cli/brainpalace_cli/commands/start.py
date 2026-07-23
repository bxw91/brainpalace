"""Start command for launching an BrainPalace server instance."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import click
from rich.console import Console
from rich.panel import Panel

from brainpalace_cli.config import resolve_project_root
from brainpalace_cli.migration import resolve_state_dir_with_fallback
from brainpalace_cli.runtime_probe import check_health as check_health  # re-export
from brainpalace_cli.runtime_probe import probe
from brainpalace_cli.xdg_paths import migrate_legacy_paths

console = Console()

STATE_DIR_NAME = ".brainpalace"
LOCK_FILE = "brainpalace.lock"
PID_FILE = "brainpalace.pid"
RUNTIME_FILE = "runtime.json"

# A live server busy indexing can miss a health probe; retry before deciding it
# is unresponsive (and never replace it with a duplicate).
EXISTING_SERVER_HEALTH_RETRIES = 3
EXISTING_SERVER_HEALTH_RETRY_DELAY = 1.0
EXISTING_SERVER_HEALTH_TIMEOUT = 5.0


def _ensure_dashboard(
    *, no_dashboard: bool, json_output: bool
) -> dict[str, Any] | None:
    """Best-effort: ensure the singleton web dashboard is up; return its state.

    Returns the dashboard info dict (``base_url`` / ``started`` / ``healthy``) or
    ``None`` when skipped or unavailable. NEVER raises — ``brainpalace start``
    must not fail because of the dashboard.

    Skips silently when ``--no-dashboard`` is passed, ``dashboard.autostart`` is
    false, or the dashboard package isn't installed (Python < 3.12). A browser is
    opened only when the dashboard is launched by this call AND stdout is an
    interactive terminal (never under ``--json`` or in CI).
    """
    if no_dashboard:
        return None
    try:
        from brainpalace_dashboard import server as _dash  # noqa: PLC0415
        from brainpalace_dashboard.config import (  # noqa: PLC0415
            load_dashboard_config,
        )
    except ImportError:
        return None  # dashboard not installed (e.g. Python 3.10/3.11)
    try:
        if not load_dashboard_config().autostart:
            return None
        open_browser = (not json_output) and sys.stdout.isatty()
        info: dict[str, Any] = _dash.ensure_running(open_browser_if_new=open_browser)
        return info
    except Exception:
        return None  # best-effort; never break `brainpalace start`


def _print_dashboard(dash: dict[str, Any] | None) -> None:
    """Print a clickable dashboard URL when one is available."""
    from brainpalace_cli.commands._dashboard_url import render_dashboard_url

    render_dashboard_url(dash, console=console)


def _dashboard_json(dash: dict[str, Any] | None) -> dict[str, Any]:
    """Compact dashboard fields for ``--json`` output (empty when unavailable)."""
    if not dash or not dash.get("base_url"):
        return {}
    return {
        "dashboard": {
            "base_url": dash["base_url"],
            "started": bool(dash.get("started")),
        }
    }


def read_bind(state_dir: Path) -> dict[str, Any]:
    """Read bind configuration from ``config.yaml`` (project → global merge).

    Calls ``load_merged_config_dict`` with the project file so global XDG
    ``config.yaml`` bind keys are inherited for any key the project omits —
    same ``code < global < project`` precedence as every other config block.
    Returns all four bind keys with their code defaults so call-sites can use
    plain dict access without worrying about missing keys.
    """
    from brainpalace_server.config.bind_config import BindConfig  # noqa: PLC0415
    from brainpalace_server.config.provider_config import (  # noqa: PLC0415
        load_merged_config_dict,
    )

    config_path = state_dir / "config.yaml"
    merged = load_merged_config_dict(config_path if config_path.exists() else None)
    block = merged.get("bind") if isinstance(merged, dict) else None
    if not isinstance(block, dict):
        block = {}
    fields = {k: v for k, v in block.items() if k in BindConfig.model_fields}
    try:
        cfg = BindConfig(**fields)
    except (ValueError, TypeError):
        cfg = BindConfig()
    return {
        "bind_host": cfg.bind_host,
        "port_range_start": cfg.port_range_start,
        "port_range_end": cfg.port_range_end,
        "auto_port": cfg.auto_port,
    }


def read_runtime(state_dir: Path) -> dict[str, Any] | None:
    """Read runtime state from state directory."""
    runtime_path = state_dir / RUNTIME_FILE
    if not runtime_path.exists():
        return None
    try:
        result: dict[str, Any] = json.loads(runtime_path.read_text())
        return result
    except Exception:
        return None


def write_runtime(state_dir: Path, runtime: dict[str, Any]) -> None:
    """Write runtime state to state directory."""
    runtime_path = state_dir / RUNTIME_FILE
    runtime_path.write_text(json.dumps(runtime, indent=2))


def delete_runtime(state_dir: Path) -> None:
    """Delete runtime state file."""
    runtime_path = state_dir / RUNTIME_FILE
    if runtime_path.exists():
        runtime_path.unlink()


def is_process_alive(pid: int) -> bool:
    """Check if a process is alive."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it


def is_stale(state_dir: Path) -> bool:
    """Check if the lock is stale (PID no longer alive)."""
    pid_path = state_dir / PID_FILE
    if not pid_path.exists():
        return True
    try:
        pid = int(pid_path.read_text().strip())
        return not is_process_alive(pid)
    except (ValueError, OSError):
        return True


def cleanup_stale(state_dir: Path) -> None:
    """Clean up stale pid and runtime files.

    Deliberately does NOT remove ``brainpalace.lock``. A running server holds an
    flock on that file's inode; unlinking it lets a second server create a fresh
    inode and acquire the lock, defeating the OS single-instance guarantee. A
    genuinely dead server's flock is released by the OS, so the next server
    reclaims the lock by opening the same path — no unlink required.
    """
    for fname in [PID_FILE, RUNTIME_FILE]:
        fpath = state_dir / fname
        if fpath.exists():
            try:
                fpath.unlink()
            except OSError:
                pass


def classify_existing_server(
    runtime: dict[str, Any] | None,
    *,
    alive_fn: Any,
    probe_fn: Any,
    expected_root: str | Path,
) -> str:
    """Decide what to do about a recorded server, given liveness + identity.

    ``probe_fn`` is the three-valued :func:`brainpalace_cli.runtime_probe.probe`
    (or a test double with the same signature): ``probe_fn(base_url,
    expected_root) -> "mine" | "other" | "down"``.

    Returns one of:
        - ``"running"``      pid alive and probe says "mine" -> report and reuse.
        - ``"unresponsive"``  pid alive but probe says "down" -> a live server
          exists (likely busy indexing); the caller MUST NOT wipe its state and
          spawn a second server on another port. This is the duplicate-server
          incident guard.
        - ``"stale"``        no runtime, pid dead, OR probe says "other" (a
          DIFFERENT project's server answered here, e.g. a copied
          ``runtime.json`` pointing at the original's live server) -> safe (and
          for "other", necessary) to clean up and start fresh.
    """
    if not runtime:
        return "stale"
    pid = runtime.get("pid", 0)
    if pid and alive_fn(pid):
        result = probe_fn(runtime.get("base_url", ""), expected_root)
        if result == "mine":
            return "running"
        if result == "other":
            return "stale"
        return "unresponsive"
    return "stale"


def find_reusable_server(project_root: Path) -> str | None:
    """Return the base_url of a live registry server for this project, else None.

    Complements :func:`classify_existing_server` (which reads the project's own
    runtime.json) by also honouring the global registry, so a server started
    from a different install surface (source venv vs pipx) is reused instead of
    duplicated on a climbed port.

    NOTE (A2, defensive-only): identity-checked via ``probe`` for correctness,
    but this path is inert today — the global registry entry carries only
    ``{state_dir, project_name}`` (the single writer never records pid/
    base_url), so ``entry.get("pid")``/``base_url`` are always empty and this
    never actually returns a reuse URL. The real start-side reuse path is
    ``classify_existing_server`` via ``runtime.json``.
    """
    from brainpalace_cli.commands.list_cmd import get_registry

    resolved_root = Path(project_root).resolve()
    entry = get_registry().get(str(resolved_root))
    if not isinstance(entry, dict):
        return None
    pid = entry.get("pid", 0)
    base_url = entry.get("base_url", "")
    if (
        pid
        and is_process_alive(pid)
        and base_url
        and probe(base_url, resolved_root) == "mine"
    ):
        return str(base_url)
    return None


class ServerAlreadyRunningError(RuntimeError):
    """Raised when a healthy server for the same project is already running.

    Carries the discovered ``base_url`` so the caller can report it instead of
    spawning a duplicate (which would double-index the shared data dir).
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(f"Server already running for this project at {base_url}")
        self.base_url = base_url


def fetch_health(base_url: str, timeout: float = 2.0) -> dict[str, Any] | None:
    """GET ``/health/`` and return the parsed body, or None if unreachable."""
    try:
        req = Request(f"{base_url}/health/", method="GET")
        with urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data: dict[str, Any] = json.loads(resp.read())
                return data
    except Exception:
        return None
    return None


def find_same_project_server(
    host: str,
    project_root: str | Path,
    start_port: int,
    end_port: int,
    *,
    probe: Any = fetch_health,
) -> str | None:
    """Scan the port range for a healthy server already serving ``project_root``.

    Returns the matching ``base_url`` or None. A server for a different project
    is ignored (the caller may legitimately bind a free port alongside it).
    """
    target = str(project_root)
    for port in range(start_port, end_port + 1):
        base_url = f"http://{host}:{port}"
        data = probe(base_url)
        if data and data.get("project_root") == target:
            return base_url
    return None


def find_available_port(host: str, start_port: int, end_port: int) -> int | None:
    """Find an available port in the given range."""
    for port in range(start_port, end_port + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                return port
        except OSError:
            continue
    return None


def update_registry(project_root: Path, state_dir: Path) -> None:
    """Add project to the global registry via the single locked server writer."""
    from brainpalace_server import registry  # CLI -> server import (allowed)

    registry.upsert_entry(project_root, state_dir)


def resolve_bind_port(config: dict[str, Any], bind_host: str, port: int | None) -> int:
    """Resolve the bind port from an explicit override, auto-port scan, or config.

    Raises:
        RuntimeError: when auto_port is enabled but no free port exists in range.
    """
    if port:
        return port
    if config.get("auto_port", True):
        start_port = config.get("port_range_start", 8000)
        end_port = config.get("port_range_end", 8100)
        available_port = find_available_port(bind_host, start_port, end_port)
        if available_port is None:
            raise RuntimeError(f"No available port in range {start_port}-{end_port}")
        return available_port
    return int(config.get("port_range_start", 8000))


def _rotate_if_oversized(path: Path, max_bytes: int, backups: int) -> None:
    """Size-rotate a captured stdout/stderr redirect file at spawn time.

    The server's stdout/stderr is appended to ``logs/server.log`` /
    ``logs/server.err`` for the whole process lifetime — unrotated, those grow
    without bound (the stderr copy reached tens of MB). Rotate when the file is
    over ``max_bytes``: ``x`` -> ``x.1`` -> ``x.2`` …, discarding past
    ``backups``. No-op when the file is small or absent.
    """
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return
        oldest = path.with_name(f"{path.name}.{backups}")
        if oldest.exists():
            oldest.unlink()
        for i in range(backups - 1, 0, -1):
            src = path.with_name(f"{path.name}.{i}")
            if src.exists():
                src.rename(path.with_name(f"{path.name}.{i + 1}"))
        path.rename(path.with_name(f"{path.name}.1"))
    except OSError:
        pass  # never block a server launch on log rotation


def build_server_command(bind_host: str, bind_port: int) -> list[str]:
    """The single place the uvicorn server argv is constructed."""
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "brainpalace_server.api.main:app",
        "--host",
        bind_host,
        "--port",
        str(bind_port),
    ]


def _sigterm_quietly(process: Any) -> None:
    """SIGTERM a spawned child if it's still alive, tolerating the reap race
    (it may exit between the poll and the kill → ProcessLookupError)."""
    try:
        if process.poll() is None:
            os.kill(process.pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass


def _child_hit_addr_in_use(stderr_log: Path, offset: int) -> bool:
    """True when the just-exited server child failed because its port was already
    bound. uvicorn/asyncio prints ``[Errno 98] ... address already in use`` on
    that path. Reads only from ``offset`` (the log size captured just before THIS
    attempt's spawn) so a *previous* attempt's message isn't mistaken for this
    child's — distinguishing a lost port race (retry elsewhere) from a genuine
    startup crash (retrying won't help)."""
    try:
        with stderr_log.open("r", errors="replace") as f:
            f.seek(offset)
            tail = f.read().lower()
    except OSError:
        return False
    return "address already in use" in tail or "errno 98" in tail


def _wait_until_owned(
    base_url: str,
    project_root: str | Path,
    process: Any,
    stderr_log: Path,
    err_offset: int,
    timeout: int,
    *,
    probe_fn: Any = None,
) -> str:
    """Wait until *this project* owns ``base_url``. Identity-checked, unlike a
    bare reachability poll: a 200 from a DIFFERENT project's server on the same
    port is a lost race, not success.

    Returns:
        ``"mine"``     — our server is up and answers for ``project_root``.
        ``"conflict"`` — another project won this port (identity ``"other"``, or
                         our child died binding it with EADDRINUSE); the caller
                         should retry on the next free port.

    Raises:
        RuntimeError — our child crashed for a NON-port reason (bad config,
            import error), or nothing became healthy within ``timeout`` and no
            other owner appeared. Retrying another port would not help.
    """
    _probe = probe_fn if probe_fn is not None else probe
    start_time = time.time()
    while time.time() - start_time < timeout:
        result = _probe(base_url, project_root, timeout=2.0)
        if result == "mine":
            return "mine"
        if result == "other":
            return "conflict"  # a different project answered — we lost the race
        # result == "down": not listening yet, or our child already exited.
        if process.poll() is not None:
            if _child_hit_addr_in_use(stderr_log, err_offset):
                return "conflict"
            raise RuntimeError(
                f"Server process exited during startup; check {stderr_log}"
            )
        time.sleep(0.5)
    _sigterm_quietly(process)
    raise RuntimeError(
        f"Server did not become healthy within {timeout}s at {base_url}; "
        f"check {stderr_log}"
    )


def launch_server(
    project_root: Path,
    state_dir: Path,
    host: str | None = None,
    port: int | None = None,
    timeout: int = 120,
    strict: bool = False,
    no_dashboard: bool = False,
) -> dict[str, Any]:
    """Resolve bind host/port, spawn the uvicorn server, persist runtime.json,
    update the global registry, and return the runtime dict.

    Pure callable — no Click, no console printing. This is the single source of
    truth for the daemonized server-spawn path; ``start_command`` calls it.

    Raises:
        RuntimeError: on port exhaustion, if the process dies during startup, or
            if the server fails its health check within ``timeout`` seconds.
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    config = read_bind(state_dir)
    bind_host = host or config.get("bind_host", "127.0.0.1")

    # Defense-in-depth: never spawn a second server for the same project, even
    # when runtime.json is missing or stale. Probe the port range for a healthy
    # server already serving this project_root and refuse if one exists.
    scan_start = config.get("port_range_start", 8000)
    scan_end = config.get("port_range_end", 8100)
    existing = find_same_project_server(bind_host, project_root, scan_start, scan_end)
    if existing:
        raise ServerAlreadyRunningError(existing)

    env = os.environ.copy()
    env["BRAINPALACE_PROJECT_ROOT"] = str(project_root)
    env["BRAINPALACE_STATE_DIR"] = str(state_dir)
    if strict:
        env["BRAINPALACE_STRICT_MODE"] = "true"
    if no_dashboard:
        # Scope the opt-out to this server's lifetime so its self-heal heartbeat
        # won't re-spawn a dashboard behind --no-dashboard (see self_heal.py).
        env["BRAINPALACE_NO_DASHBOARD"] = "true"

    log_dir = state_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / "server.log"
    stderr_log = log_dir / "server.err"

    # Cap the captured redirect logs (5MB x 2 backups each) so they can't grow
    # without bound across the daemon's lifetime.
    _rotate_if_oversized(stdout_log, max_bytes=5_000_000, backups=2)
    _rotate_if_oversized(stderr_log, max_bytes=5_000_000, backups=2)

    # Port selection is inherently racy: find_available_port binds a probe
    # socket, closes it, and returns the number, but uvicorn only binds ~1-2s
    # later — so two concurrent `bp start` for different projects can both pick
    # the same port. The wait below is IDENTITY-checked (accepts only "mine"),
    # and on a lost race (another project owns the port, or our child died with
    # EADDRINUSE) we retry on the next free port instead of falsely adopting the
    # foreign server. An explicit --port (or auto_port off) is honored exactly
    # once — a conflict there is a hard error, not a scan.
    auto_port = bool(config.get("auto_port", True)) and port is None
    scan_from = scan_start
    max_attempts = 5 if auto_port else 1
    for _attempt in range(max_attempts):
        if auto_port:
            bind_port_opt = find_available_port(bind_host, scan_from, scan_end)
            if bind_port_opt is None:
                raise RuntimeError(
                    f"No available port in range {scan_start}-{scan_end}"
                )
            bind_port = bind_port_opt
        else:
            bind_port = resolve_bind_port(config, bind_host, port)
        base_url = f"http://{bind_host}:{bind_port}"
        server_cmd = build_server_command(bind_host, bind_port)

        # Record the log size BEFORE spawning so _wait_until_owned can tell this
        # child's EADDRINUSE from a previous attempt's (the file is appended).
        err_offset = stderr_log.stat().st_size if stderr_log.exists() else 0

        with (
            open(stdout_log, "a") as stdout_f,
            open(stderr_log, "a") as stderr_f,
        ):
            process = subprocess.Popen(
                server_cmd,
                env=env,
                stdout=stdout_f,
                stderr=stderr_f,
                start_new_session=True,
            )

        runtime: dict[str, Any] = {
            "schema_version": "1.0",
            "mode": "project",
            "project_root": str(project_root),
            "instance_id": uuid4().hex[:12],
            "base_url": base_url,
            "bind_host": bind_host,
            "port": bind_port,
            "pid": process.pid,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "log_file": str(stdout_log),
        }
        write_runtime(state_dir, runtime)
        update_registry(project_root, state_dir)
        # Record in the durable known-projects store so the project stays listed
        # (and Start-able) in the dashboard fleet after it stops — "every project
        # ever started" persists until its directory is deleted from disk.
        try:
            from brainpalace_cli import known_projects

            known_projects.remember(project_root, state_dir, project_root.name)
        except OSError:
            pass  # never fail a server launch over the known-projects bookkeeping

        outcome = _wait_until_owned(
            base_url, project_root, process, stderr_log, err_offset, timeout
        )
        if outcome == "mine":
            return runtime

        # Lost the port race. Reap our (usually already-dead) child, drop the
        # stale runtime.json, and — auto-port only — retry on the next port up.
        _sigterm_quietly(process)
        delete_runtime(state_dir)
        if not auto_port:
            raise RuntimeError(
                f"Port {bind_port} on {bind_host} was taken by another server "
                f"during startup; check {stderr_log}"
            )
        scan_from = bind_port + 1

    raise RuntimeError(
        f"Could not claim a free port after {max_attempts} attempts "
        f"(a concurrent start may be racing); check {stderr_log}"
    )


@click.command("start")
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project path (default: auto-detect project root)",
)
@click.option(
    "--host",
    default=None,
    help="Server bind host (overrides config)",
)
@click.option(
    "--port",
    type=int,
    default=None,
    help="Server port (overrides config)",
)
@click.option(
    "--foreground",
    "-f",
    is_flag=True,
    help="Run in foreground (don't daemonize)",
)
@click.option(
    "--timeout",
    type=int,
    default=120,
    help="Startup timeout in seconds (default: 120)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--strict",
    is_flag=True,
    help="Enable strict mode: fail on critical provider configuration errors",
)
@click.option(
    "--no-dashboard",
    is_flag=True,
    help="Do not bring up the web dashboard from this server, by any path "
    "(overrides dashboard.autostart; also stops the server's self-heal from "
    "re-spawning one for its lifetime)",
)
@click.option(
    "--no-activate",
    is_flag=True,
    hidden=True,
    help="Internal: do NOT clear the activation marker (cli.await_first_start). "
    "Passed by passive callers (the SessionStart hook) so only a genuine manual "
    "start activates a deferred project.",
)
def start_command(
    path: str | None,
    host: str | None,
    port: int | None,
    foreground: bool,
    timeout: int,
    json_output: bool,
    strict: bool,
    no_dashboard: bool,
    no_activate: bool,
) -> None:
    """Start an BrainPalace server for this project.

    Spawns a new server instance bound to the project. If a server is
    already running for this project, reports its URL instead.

    On Python 3.12+ this also ensures the web dashboard (a single control plane
    for all projects) is running and prints its URL — opening a browser only
    when it launches one. Disable per-run with --no-dashboard (which also stops
    this server's self-heal from re-spawning a dashboard, so "no dashboard"
    holds for its whole lifetime), or persistently with dashboard.autostart:
    false in the XDG config.

    \b
    Examples:
      brainpalace start                    # Start server (+ dashboard on 3.12+)
      brainpalace start --port 8080        # Start on specific port
      brainpalace start --strict           # Fail on missing API keys
      brainpalace start --foreground       # Run in foreground
      brainpalace start --no-dashboard     # Don't auto-start the dashboard
      brainpalace start --path /my/project # Start for specific project
    """
    try:
        # Trigger one-time migration from legacy ~/.brainpalace to XDG dirs
        migrate_legacy_paths()

        # Best-effort: migrate an already-installed legacy "fat" SessionStart
        # hook to the thin shim (logic now lives in `brainpalace hook`). Only
        # touches a hook the user already has; never installs one. After this
        # the shim can never go stale. Must not break `start`.
        try:
            from .session_hooks import migrate_legacy_sessionstart_hook

            migrate_legacy_sessionstart_hook(Path.home())
        except Exception:
            pass

        # Resolve project root
        if path:
            project_root = Path(path).resolve()
        else:
            project_root = resolve_project_root()

        state_dir = resolve_state_dir_with_fallback(project_root)

        # Check if initialized
        if not state_dir.exists():
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "error": "Project not initialized",
                            "hint": "Run 'brainpalace init' first",
                        }
                    )
                )
            else:
                console.print(
                    f"[red]Error:[/] Project not initialized at {project_root}"
                )
                console.print(
                    "[dim]Run 'brainpalace init' to initialize the project.[/]"
                )
            raise SystemExit(1)

        def _activate_on_success() -> None:
            """Clear the activation gate marker on a genuine manual start.

            A successful ``brainpalace start`` (or dashboard "Start") is THE
            activation event for a deferred (plugin-configured) project: future
            sessions then autostart normally. ``--no-activate`` (passive callers)
            skips this so only a user-typed start activates. Best-effort.
            """
            if no_activate:
                return
            try:
                from ..config_schema import (
                    read_await_first_start,
                    write_await_first_start,
                )

                if read_await_first_start(state_dir):
                    write_await_first_start(state_dir, False)
            except Exception:  # noqa: BLE001 — flip is best-effort, never blocks
                pass

        # Read configuration
        config = read_bind(state_dir)

        # Cross-install reuse: a live, healthy server for THIS project may be
        # recorded in the GLOBAL registry even when this project's runtime.json
        # is missing or stale (e.g. it was started from a different install
        # surface). Reuse it instead of spawning a duplicate that would climb to
        # a new port and double-write the shared data dir.
        reusable = find_reusable_server(project_root)
        if reusable:
            _activate_on_success()
            dash = _ensure_dashboard(no_dashboard=no_dashboard, json_output=json_output)
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "already_running",
                            "base_url": reusable,
                            "project_root": str(project_root),
                            **_dashboard_json(dash),
                        }
                    )
                )
            else:
                console.print(f"[green]Reusing running server:[/] {reusable}")
                _print_dashboard(dash)
            return

        # Check for existing runtime. A live server must never be replaced by a
        # second one on another port (that duplicates writes to the shared data
        # dir). Retry health a few times first — a server busy indexing can miss
        # a single 3s health probe without being dead.
        runtime = read_runtime(state_dir)
        if runtime:
            action = classify_existing_server(
                runtime,
                alive_fn=is_process_alive,
                probe_fn=probe,
                expected_root=project_root,
            )
            pid = runtime.get("pid", 0)
            base_url = runtime.get("base_url", "")

            if action == "unresponsive":
                for _ in range(EXISTING_SERVER_HEALTH_RETRIES):
                    time.sleep(EXISTING_SERVER_HEALTH_RETRY_DELAY)
                    if not is_process_alive(pid):
                        action = "stale"
                        break
                    # Re-probe for IDENTITY, not a bare 200 — a different
                    # project's server may have come up on this port while we
                    # waited (rare, but "other" must not be reported "running").
                    retry_result = probe(
                        base_url, project_root, timeout=EXISTING_SERVER_HEALTH_TIMEOUT
                    )
                    if retry_result == "mine":
                        action = "running"
                        break
                    if retry_result == "other":
                        action = "stale"
                        break

            if action == "running":
                _activate_on_success()
                dash = _ensure_dashboard(
                    no_dashboard=no_dashboard, json_output=json_output
                )
                if json_output:
                    click.echo(
                        json.dumps(
                            {
                                "status": "already_running",
                                "base_url": base_url,
                                "pid": pid,
                                "project_root": str(project_root),
                                **_dashboard_json(dash),
                            }
                        )
                    )
                else:
                    console.print(
                        Panel(
                            f"[yellow]Server already running![/]\n\n"
                            f"[bold]URL:[/] {base_url}\n"
                            f"[bold]PID:[/] {pid}\n"
                            f"[bold]Project:[/] {project_root}",
                            title="Server Running",
                            border_style="yellow",
                        )
                    )
                    _print_dashboard(dash)
                return

            if action == "unresponsive":
                # Alive but not answering: refuse rather than spawn a duplicate.
                msg = (
                    f"Server process {pid} is alive but not responding at "
                    f"{base_url}. Run 'brainpalace restart' (or 'brainpalace stop') "
                    f"to recover; refusing to start a second server on the same "
                    f"project (would duplicate the index)."
                )
                if json_output:
                    click.echo(
                        json.dumps({"error": "Server unresponsive", "detail": msg})
                    )
                else:
                    console.print(f"[red]Error:[/] {msg}")
                raise SystemExit(1)

            # Genuinely stale (pid dead) — clean up pid/runtime and start fresh.
            if not json_output:
                console.print("[dim]Cleaning up stale server state...[/]")
            cleanup_stale(state_dir)

        # Determine bind host and port (foreground path resolves inline; the
        # daemonized path is fully delegated to launch_server below).
        bind_host = host or config.get("bind_host", "127.0.0.1")

        if foreground:
            try:
                bind_port = resolve_bind_port(config, bind_host, port)
            except RuntimeError as e:
                if json_output:
                    click.echo(json.dumps({"error": str(e)}))
                else:
                    console.print(f"[red]Error:[/] {e}")
                raise SystemExit(1) from e

            base_url = f"http://{bind_host}:{bind_port}"

            if not json_output:
                console.print(f"[dim]Starting server on {base_url}...[/]")

            # Build server command
            server_cmd = build_server_command(bind_host, bind_port)

            # Set environment variables for server
            env = os.environ.copy()
            env["BRAINPALACE_PROJECT_ROOT"] = str(project_root)
            env["BRAINPALACE_STATE_DIR"] = str(state_dir)
            if strict:
                env["BRAINPALACE_STRICT_MODE"] = "true"
            if no_dashboard:
                # Scope the opt-out to this server's lifetime so its self-heal
                # heartbeat won't re-spawn a dashboard (see self_heal.py).
                env["BRAINPALACE_NO_DASHBOARD"] = "true"

            # Write runtime state even in foreground mode so CLI can discover the URL
            from datetime import datetime, timezone
            from uuid import uuid4

            runtime_state = {
                "schema_version": "1.0",
                "mode": "project",
                "project_root": str(project_root),
                "instance_id": uuid4().hex[:12],
                "base_url": base_url,
                "bind_host": bind_host,
                "port": bind_port,
                "pid": os.getpid(),  # Current PID (will be replaced by exec)
                "started_at": datetime.now(timezone.utc).isoformat(),
                "foreground": True,  # Mark as foreground for cleanup detection
            }
            write_runtime(state_dir, runtime_state)

            # Update global registry
            update_registry(project_root, state_dir)
            _activate_on_success()

            dash = _ensure_dashboard(no_dashboard=no_dashboard, json_output=json_output)
            if not json_output:
                console.print(
                    Panel(
                        f"[green]Starting server in foreground[/]\n\n"
                        f"[bold]URL:[/] {base_url}\n"
                        f"[bold]Project:[/] {project_root}\n\n"
                        f"[dim]Press Ctrl+C to stop[/]",
                        title="BrainPalace Server",
                        border_style="green",
                    )
                )
                _print_dashboard(dash)
            os.execvpe(server_cmd[0], server_cmd, env)
        else:
            # Daemonize the server — single source of truth lives in launch_server.
            if not json_output:
                console.print("[dim]Starting server...[/]")
            dash = _ensure_dashboard(no_dashboard=no_dashboard, json_output=json_output)
            try:
                runtime_state = launch_server(
                    project_root=project_root,
                    state_dir=state_dir,
                    host=host,
                    port=port,
                    timeout=timeout,
                    strict=strict,
                    no_dashboard=no_dashboard,
                )
            except ServerAlreadyRunningError as e:
                # A healthy server for this project was found mid-launch (runtime
                # state was missing/stale). Report it instead of duplicating.
                _activate_on_success()
                if json_output:
                    click.echo(
                        json.dumps(
                            {
                                "status": "already_running",
                                "base_url": e.base_url,
                                "project_root": str(project_root),
                                **_dashboard_json(dash),
                            }
                        )
                    )
                else:
                    console.print(
                        Panel(
                            f"[yellow]Server already running![/]\n\n"
                            f"[bold]URL:[/] {e.base_url}\n"
                            f"[bold]Project:[/] {project_root}",
                            title="Server Running",
                            border_style="yellow",
                        )
                    )
                    _print_dashboard(dash)
                return
            except RuntimeError as e:
                stderr_log = state_dir / "logs" / "server.err"
                if json_output:
                    click.echo(
                        json.dumps(
                            {
                                "error": "Server failed to start",
                                "detail": str(e),
                                "log_file": str(stderr_log),
                            }
                        )
                    )
                else:
                    console.print(f"[red]Error:[/] {e}")
                    console.print(f"[dim]Check logs: {stderr_log}[/]")
                raise SystemExit(1) from e

            base_url = runtime_state["base_url"]
            pid = runtime_state["pid"]
            _activate_on_success()
            stdout_log = runtime_state.get(
                "log_file", str(state_dir / "logs" / "server.log")
            )
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "started",
                            "base_url": base_url,
                            "pid": pid,
                            "project_root": str(project_root),
                            "log_file": stdout_log,
                            **_dashboard_json(dash),
                        },
                        indent=2,
                    )
                )
            else:
                console.print(
                    Panel(
                        f"[green]Server started successfully![/]\n\n"
                        f"[bold]PID:[/] {pid}\n"
                        f"[bold]URL:[/] {base_url}\n"
                        f"[bold]Project:[/] {project_root}",
                        title="BrainPalace Server Running",
                        border_style="green",
                    )
                )
                _print_dashboard(dash)

    except PermissionError as e:
        if json_output:
            click.echo(json.dumps({"error": f"Permission denied: {e}"}))
        else:
            console.print(f"[red]Permission Error:[/] {e}")
        raise SystemExit(1) from e
    except OSError as e:
        if json_output:
            click.echo(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error:[/] {e}")
        raise SystemExit(1) from e
