"""Stop command for stopping an BrainPalace server instance."""

import json
import os
import signal
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import click
from rich.console import Console

from brainpalace_cli.config import resolve_project_root
from brainpalace_cli.migration import resolve_state_dir_with_fallback
from brainpalace_cli.runtime_probe import probe
from brainpalace_cli.xdg_paths import get_registry_path

console = Console()

STATE_DIR_NAME = ".brainpalace"
LOCK_FILE = "brainpalace.lock"
PID_FILE = "brainpalace.pid"
RUNTIME_FILE = "runtime.json"


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


def delete_runtime(state_dir: Path) -> None:
    """Delete runtime state file."""
    runtime_path = state_dir / RUNTIME_FILE
    if runtime_path.exists():
        runtime_path.unlink()


def cleanup_state_files(state_dir: Path) -> None:
    """Clean up all state files after stop."""
    for fname in [LOCK_FILE, PID_FILE, RUNTIME_FILE]:
        fpath = state_dir / fname
        if fpath.exists():
            try:
                fpath.unlink()
            except OSError:
                pass


def is_process_alive(pid: int) -> bool:
    """Check if a process is alive."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it


def wait_for_process_exit(pid: int, timeout: float = 10.0) -> bool:
    """Wait for a process to exit.

    Args:
        pid: Process ID to wait for.
        timeout: Maximum time to wait in seconds.

    Returns:
        True if process exited, False if timeout reached.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not is_process_alive(pid):
            return True
        time.sleep(0.2)
    return False


def remove_from_registry(project_root: Path) -> None:
    """Remove project from global registry."""
    registry_path = get_registry_path()
    if not registry_path.exists():
        return

    try:
        registry = json.loads(registry_path.read_text())
        if str(project_root) in registry:
            del registry[str(project_root)]
            registry_path.write_text(json.dumps(registry, indent=2))
    except Exception:
        pass


def resolve_project_root_from_url(url: str, timeout: float = 2.0) -> Path:
    """Resolve project_root by querying the server's /runtime/ endpoint.

    Args:
        url: Server base URL (e.g. http://127.0.0.1:8001).
        timeout: HTTP request timeout in seconds.

    Returns:
        Resolved project_root Path.

    Raises:
        OSError: If the server is unreachable or returns a bad response.
    """
    base = url.rstrip("/")
    req = Request(f"{base}/runtime/", method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise OSError(
                    f"Server at {url} returned HTTP {resp.status} from /runtime/"
                )
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise OSError(
            f"Failed to reach {url}/runtime/ — server may be down: {exc}"
        ) from exc

    project_root = data.get("project_root")
    if not project_root:
        raise OSError(
            f"Server at {url} did not return a project_root in /runtime/ response"
        )
    return Path(project_root).resolve()


@click.command("stop")
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project path (default: auto-detect project root)",
)
@click.option(
    "--url",
    "url",
    envvar="BRAINPALACE_URL",
    default=None,
    help=(
        "Server URL — resolves project_root via GET /runtime/ "
        "(ignored when --path is given)"
    ),
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help=(
        "Skip the graceful-shutdown wait — SIGKILL immediately. With --all, "
        "also skips the orphan-reaper's grace window (SIGKILL escalation "
        "runs either way)."
    ),
)
@click.option(
    "--timeout",
    type=int,
    default=10,
    help="Timeout for graceful shutdown in seconds (default: 10)",
)
@click.option(
    "--all",
    "stop_all",
    is_flag=True,
    help="Also reap orphan server processes not referenced by the registry.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def stop_command(
    path: str | None,
    url: str | None,
    force: bool,
    timeout: int,
    stop_all: bool,
    json_output: bool,
) -> None:
    """Stop the BrainPalace server for this project.

    Sends SIGTERM to the server process and waits for graceful shutdown.
    If --force is specified and the process doesn't exit within the timeout,
    sends SIGKILL.

    \b
    Examples:
      brainpalace stop                              # Stop server for current project
      brainpalace stop --force                      # Force stop if graceful fails
      brainpalace stop --path /my/project           # Stop specific project's server
      brainpalace stop --url http://127.0.0.1:8001  # Stop server by URL
      brainpalace stop --all                        # Reap orphan server processes
      brainpalace stop --all --force                # Reap orphans, skip grace window
    """
    if stop_all:
        from brainpalace_cli.commands.reap import reap_orphans

        outcome = reap_orphans(grace=0.0) if force else reap_orphans()
        reaped, survived = outcome.reaped, outcome.survived
        if json_output:
            click.echo(
                json.dumps(
                    {"reaped_pids": reaped, "surviving_pids": survived}, indent=2
                )
            )
        else:
            if reaped:
                console.print(
                    f"[green]Reaped {len(reaped)} orphan server process(es):[/] "
                    f"{', '.join(map(str, reaped))}"
                )
            else:
                console.print("[dim]No orphan server processes found.[/]")
            if survived:
                console.print(
                    f"[red]Still alive after SIGKILL:[/] "
                    f"{', '.join(map(str, survived))}"
                )
        return
    try:
        # Resolve project root
        if path:
            project_root = Path(path).resolve()
        elif url:
            try:
                project_root = resolve_project_root_from_url(url)
            except OSError as exc:
                if json_output:
                    click.echo(
                        json.dumps(
                            {
                                "error": "connection_error",
                                "url": url,
                                "message": str(exc),
                            }
                        )
                    )
                else:
                    console.print(f"[red]Connection Error:[/] {exc}")
                raise SystemExit(7) from exc
        else:
            project_root = resolve_project_root()

        state_dir = resolve_state_dir_with_fallback(project_root)

        # Check if state directory exists
        if not state_dir.exists():
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "error": "No BrainPalace state found",
                            "project_root": str(project_root),
                        }
                    )
                )
            else:
                console.print(
                    f"[yellow]No BrainPalace state found for:[/] {project_root}"
                )
            raise SystemExit(1)

        # Read runtime state
        runtime = read_runtime(state_dir)
        if not runtime:
            # Check if there's a stale PID file
            pid_path = state_dir / PID_FILE
            if pid_path.exists():
                try:
                    pid = int(pid_path.read_text().strip())
                    if is_process_alive(pid):
                        if json_output:
                            click.echo(
                                json.dumps(
                                    {
                                        "status": "stopping",
                                        "message": "Found stale PID, stopping",
                                        "pid": pid,
                                    }
                                )
                            )
                        else:
                            console.print(
                                f"[dim]Found stale PID {pid}, attempting to stop...[/]"
                            )
                        runtime = {"pid": pid}
                except (ValueError, OSError):
                    pass

            if not runtime:
                cleanup_state_files(state_dir)
                if json_output:
                    click.echo(
                        json.dumps(
                            {
                                "status": "not_running",
                                "message": "No server running",
                                "project_root": str(project_root),
                            }
                        )
                    )
                else:
                    console.print("[yellow]No server running for this project.[/]")
                return

        pid = runtime.get("pid", 0)

        if not pid:
            cleanup_state_files(state_dir)
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "not_running",
                            "message": "No PID in runtime state",
                        }
                    )
                )
            else:
                console.print("[yellow]No server PID found in runtime state.[/]")
            return

        # Check if process is alive
        if not is_process_alive(pid):
            cleanup_state_files(state_dir)
            remove_from_registry(project_root)
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "already_stopped",
                            "message": "Server process already stopped",
                            "pid": pid,
                        }
                    )
                )
            else:
                console.print(f"[yellow]Server process (PID {pid}) already stopped.[/]")
                console.print("[dim]Cleaned up state files.[/]")
            return

        # Cross-project-kill guard (A4, HIGH severity): a copied .brainpalace/
        # carries the ORIGINAL project's pid/base_url in its runtime.json. A
        # live pid alone can't tell "my server" from "someone else's server
        # that happens to be alive" — only /health/'s project_root can. Only
        # runs when runtime came from runtime.json (has a base_url); the bare
        # stale-PID-file fallback has no base_url to check against and is left
        # as a last resort per the spec.
        base_url = runtime.get("base_url", "")
        if base_url:
            identity = probe(base_url, project_root)
            if identity == "other":
                cleanup_state_files(state_dir)
                remove_from_registry(project_root)
                msg = (
                    "The recorded server belongs to a different project "
                    "(likely a copied .brainpalace/); not stopping it. "
                    "Cleaned up local state for this project."
                )
                if json_output:
                    click.echo(
                        json.dumps(
                            {
                                "status": "not_running_here",
                                "message": msg,
                                "project_root": str(project_root),
                                "pid": pid,
                                "base_url": base_url,
                            }
                        )
                    )
                else:
                    console.print(f"[yellow]{msg}[/]")
                return

        if not json_output:
            console.print(f"[dim]Stopping server (PID {pid})...[/]")

        # Send SIGTERM
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            # Process already gone
            pass
        except PermissionError as e:
            if json_output:
                click.echo(json.dumps({"error": f"Permission denied: {e}"}))
            else:
                console.print(f"[red]Permission denied:[/] Cannot signal PID {pid}")
            raise SystemExit(1) from e

        # Wait for graceful shutdown
        if wait_for_process_exit(pid, timeout):
            cleanup_state_files(state_dir)
            remove_from_registry(project_root)
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "stopped",
                            "message": "Server stopped gracefully",
                            "pid": pid,
                            "project_root": str(project_root),
                        },
                        indent=2,
                    )
                )
            else:
                console.print(f"[green]Server stopped gracefully (PID {pid}).[/]")
            return

        # Graceful shutdown failed
        if force:
            if not json_output:
                console.print(
                    "[yellow]Graceful shutdown timeout, sending SIGKILL...[/]"
                )

            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

            # Wait briefly for SIGKILL
            if wait_for_process_exit(pid, 5.0):
                cleanup_state_files(state_dir)
                remove_from_registry(project_root)
                if json_output:
                    click.echo(
                        json.dumps(
                            {
                                "status": "killed",
                                "message": "Server force killed",
                                "pid": pid,
                                "project_root": str(project_root),
                            },
                            indent=2,
                        )
                    )
                else:
                    console.print(f"[yellow]Server force killed (PID {pid}).[/]")
                return
            else:
                if json_output:
                    click.echo(
                        json.dumps(
                            {
                                "error": "Failed to stop server",
                                "pid": pid,
                                "message": "Process did not respond to SIGKILL",
                            }
                        )
                    )
                else:
                    console.print(f"[red]Error:[/] Failed to stop server (PID {pid})")
                raise SystemExit(1)
        else:
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "error": "Graceful shutdown timeout",
                            "pid": pid,
                            "hint": "Use --force to send SIGKILL",
                        }
                    )
                )
            else:
                console.print(f"[yellow]Graceful shutdown timeout for PID {pid}.[/]")
                console.print("[dim]Use --force to send SIGKILL.[/]")
            raise SystemExit(1)

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
