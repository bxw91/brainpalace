"""Update command — upgrade BrainPalace to the latest published version.

Detects how the CLI was installed (pipx / uv / pip) and runs the matching
upgrade. The published wheels carry the correct version straight from
``pyproject.toml``; a restart of any running server is needed for the new
code to take effect.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()


def detect_install_manager(bin_path: str | Path | None = None) -> str | None:
    """Classify how ``brainpalace`` was installed from its binary location.

    Args:
        bin_path: Path to the ``brainpalace`` executable. Defaults to the one
            resolved on ``PATH``.

    Returns:
        ``"pipx"``, ``"uv"``, ``"pip"``, or ``None`` if the binary can't be
        found at all.
    """
    if bin_path is None:
        bin_path = shutil.which("brainpalace")
    if not bin_path:
        return None
    bin_path = Path(bin_path)
    # pipx/uv drop a *symlink* (or console-script shim) in ~/.local/bin; the
    # shim path itself has no ``/pipx/`` or ``/uv/tools/`` segment. Classify the
    # symlink target and the shebang's interpreter, not just the shim's name —
    # otherwise a pipx/uv install misreads as bare pip and prints a PEP 668-
    # failing uninstall line.
    candidates = [str(bin_path)]
    try:
        candidates.append(str(bin_path.resolve()))
    except OSError:
        pass
    try:
        candidates.append(bin_path.read_text(errors="ignore").splitlines()[0])
    except (OSError, IndexError):
        pass
    blob = "\n".join(candidates)
    if "/pipx/" in blob:
        return "pipx"
    if "/uv/tools/" in blob:
        return "uv"
    return "pip"


def upgrade_argv(manager: str) -> list[str]:
    """Return the upgrade command for a given install manager.

    Each path bypasses the package manager's HTTP/index cache
    (``--no-cache-dir`` / ``--no-cache``) so an upgrade run minutes after a
    release sees the new version instead of a stale cached simple-index page
    that still resolves to the previous one.
    """
    if manager == "pipx":
        return ["pipx", "upgrade", "brainpalace-cli", "--pip-args=--no-cache-dir"]
    if manager == "uv":
        return ["uv", "tool", "upgrade", "--no-cache", "brainpalace-cli"]
    if manager == "pip":
        return [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-cache-dir",
            "brainpalace-rag",
            "brainpalace-cli",
        ]
    raise ValueError(f"unknown install manager: {manager}")


def _brainpalace_argv() -> list[str]:
    """Resolve how to invoke a nested ``brainpalace`` subcommand.

    Prefer the console script on PATH (after the upgrade this is the NEW code);
    fall back to ``python -m brainpalace_cli`` when no binary is on PATH.
    """
    exe = shutil.which("brainpalace")
    if exe:
        return [exe]
    return [sys.executable, "-m", "brainpalace_cli"]


def running_servers() -> list[str]:
    """Project roots from the registry whose server process is currently alive.

    A server counts as alive when its ``runtime.json`` pid is running or its
    ``base_url`` answers /health — mirrors how ``brainpalace list`` decides.
    """
    from brainpalace_cli.commands.list_cmd import (  # noqa: PLC0415
        check_health,
        get_registry,
        is_process_alive,
        read_runtime,
    )

    alive: list[str] = []
    for project_root, entry in get_registry().items():
        state_dir = Path(entry.get("state_dir", ""))
        if not state_dir:
            continue
        runtime = read_runtime(state_dir)
        if not runtime:
            continue
        pid = runtime.get("pid")
        base_url = runtime.get("base_url")
        if (pid and is_process_alive(pid)) or (base_url and check_health(base_url)):
            alive.append(project_root)
    return alive


def _running_instances() -> tuple[list[str], bool]:
    """Currently-alive per-project servers and whether the dashboard is up."""
    return running_servers(), dashboard_running()


def _live_summary(servers: list[str], dashboard: bool) -> str:
    """Human phrase for the live instances (e.g. '2 servers and the dashboard')."""
    parts: list[str] = []
    if servers:
        plural = "s" if len(servers) != 1 else ""
        parts.append(f"{len(servers)} server{plural}")
    if dashboard:
        parts.append("the control-plane dashboard")
    return " and ".join(parts)


def dashboard_running() -> bool:
    """True when the singleton control-plane dashboard is up (Python 3.12+)."""
    try:
        from brainpalace_dashboard.server import (  # noqa: PLC0415
            dashboard_status,
        )
    except ImportError:
        return False  # dashboard package not installed (Python < 3.12)
    try:
        return bool(dashboard_status().get("status") == "running")
    except Exception:
        return False


def _dashboard_orphan_pids() -> list[int]:
    """Live dashboard PIDs found by process scan (empty if pkg absent / off Linux).

    The dashboard pidfile tracks only one process; leaked duplicates on climbed
    ports (or from another install surface) show up only in the process table.
    """
    try:
        from brainpalace_dashboard.server import (  # noqa: PLC0415
            list_dashboard_pids,
        )
    except ImportError:
        return []
    try:
        pids: list[int] = list_dashboard_pids()
        return pids
    except Exception:
        return []


def _reap_orphan_servers() -> None:
    """SIGTERM RAG-server processes not referenced by a live registry entry."""
    try:
        from brainpalace_cli.commands.reap import reap_orphans  # noqa: PLC0415

        reap_orphans()
    except Exception:
        pass


def _run_cmd(cmd: list[str], home: str) -> subprocess.CompletedProcess[str]:
    """Run a brainpalace subcommand from ``home``, capturing output."""
    return subprocess.run(cmd, cwd=home, capture_output=True, text=True)


def _stop_all_instances(servers: list[str], *, argv: list[str], home: str) -> None:
    """Stop EVERY running instance before the upgrade.

    Registry servers are stopped by path; orphan servers (another install
    surface) and every dashboard (tracked + climbed-port strays) are reaped via
    the process-scan reapers. After this returns nothing BrainPalace is running,
    so the upgrade can't silently leave old code serving.
    """
    for project_root in servers:
        console.print(f"  [dim]stopping server[/] {project_root}")
        _run_cmd([*argv, "stop", "--path", project_root, "--json"], home)
    _reap_orphan_servers()
    console.print("  [dim]stopping dashboard[/]")
    # `dashboard stop` reaps every dashboard (tracked + strays).
    _run_cmd([*argv, "dashboard", "stop"], home)


def _restart_and_verify(
    servers: list[str], *, dashboard: bool, argv: list[str], home: str
) -> bool:
    """Restart the snapshot of instances one by one, verifying each.

    ``brainpalace start`` / ``dashboard start`` health-wait before exiting 0, so
    a zero exit IS the verification. Prints a per-instance ✓/✗ status line.
    Returns True only when every instance came back healthy.
    """
    all_ok = True
    for project_root in servers:
        res = _run_cmd(
            [*argv, "start", "--path", project_root, "--no-dashboard", "--json"],
            home,
        )
        if res.returncode == 0:
            console.print(f"  [green]✓[/] server [bold]{project_root}[/] — healthy")
        else:
            all_ok = False
            console.print(
                f"  [red]✗[/] server [bold]{project_root}[/] failed: "
                f"{res.stderr.strip() or 'see logs'}"
            )

    if dashboard:
        res = _run_cmd([*argv, "dashboard", "start", "--no-open", "--json"], home)
        if res.returncode == 0:
            from brainpalace_cli.commands._dashboard_url import render_dashboard_url

            try:
                data = json.loads(res.stdout or "{}")
            except ValueError:
                data = {}
            console.print("  [green]✓[/] dashboard — healthy")
            render_dashboard_url(
                {"base_url": data.get("base_url"), "started": True},
                console=console,
            )
        else:
            all_ok = False
            console.print(
                f"  [red]✗[/] dashboard failed: {res.stderr.strip() or 'see logs'}"
            )

    return all_ok


@click.command("update")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option(
    "--no-restart",
    is_flag=True,
    help="Upgrade only — leave running instances untouched (they keep serving "
    "OLD code until you restart them yourself).",
)
def update_command(yes: bool, no_restart: bool) -> None:
    """Upgrade BrainPalace (CLI + server + dashboard) to the latest version.

    Auto-detects pipx / uv / pip. Default flow is **stop-all → upgrade →
    restart-and-verify**: every running instance is stopped first (so the upgrade
    can never silently leave old code serving), then the same set is restarted
    one by one with a per-instance health check. If the upgrade fails, you are
    told loudly that nothing is running and you are NOT on the new version. Use
    ``--no-restart`` to upgrade without touching running instances.
    """
    manager = detect_install_manager()
    if manager is None:
        console.print(
            "[red]Could not detect how BrainPalace was installed.[/]\n"
            "Upgrade manually, e.g.:\n"
            "  [bold]pip install --upgrade brainpalace-rag brainpalace-cli[/]"
        )
        raise SystemExit(1)

    argv = upgrade_argv(manager)
    console.print(f"[dim]Detected install via [bold]{manager}[/].[/]")
    console.print(f"Will run: [bold]{' '.join(argv)}[/]")

    # Snapshot what is running BEFORE we touch anything, so we restore exactly
    # this set afterwards. Dashboard counts as live if tracked OR an orphan
    # (climbed-port stray) exists — both get reaped on stop.
    servers, dash = _running_instances()
    dashboard_live = dash or bool(_dashboard_orphan_pids())
    home = str(Path.home())
    bp = _brainpalace_argv()

    # --- escape hatch: upgrade without disrupting anything ---------------------
    if no_restart:
        if (servers or dashboard_live) and not yes:
            console.print(
                f"[yellow]Note:[/] {_live_summary(servers, dashboard_live)} will "
                "keep serving the OLD code until you restart them."
            )
        if not yes and not click.confirm("Upgrade now (no restart)?", default=True):
            console.print("[dim]Aborted.[/]")
            return
        result = subprocess.run(argv, cwd=home)
        if result.returncode != 0:
            console.print("[red]Upgrade failed.[/] See the output above.")
            raise SystemExit(result.returncode)
        console.print("\n[green]Upgrade complete.[/]")
        if servers or dashboard_live:
            console.print(
                "[yellow]Running instances still serve the OLD code.[/] Restart "
                "them: [bold]brainpalace stop && brainpalace start[/] "
                "(and [bold]brainpalace dashboard start[/])."
            )
        return

    # --- default: stop-all -> upgrade -> restart-and-verify --------------------
    if servers or dashboard_live:
        what = _live_summary(servers, dashboard_live)
        console.print(
            f"[yellow]This will stop {what}[/], upgrade, then restart and verify "
            "each one."
        )
        prompt = f"Stop {what}, upgrade, and restart?"
    else:
        prompt = "Upgrade now?"
    if not yes and not click.confirm(prompt, default=True):
        console.print("[dim]Aborted — nothing stopped.[/]")
        return

    if servers or dashboard_live:
        console.print("[bold]Stopping all instances…[/]")
        _stop_all_instances(servers, argv=bp, home=home)

    # Run from $HOME so pipx doesn't mistake 'brainpalace-cli' for a local path
    # when the cwd happens to contain a matching subdirectory.
    result = subprocess.run(argv, cwd=home)
    if result.returncode != 0:
        if servers or dashboard_live:
            console.print(
                "\n[red bold]Upgrade FAILED — all instances were stopped first.[/]\n"
                "[red]Nothing is running and you are NOT on the new version.[/]\n"
                "Restore the previous version's services:\n"
                "  [bold]brainpalace start[/] (per project)\n"
                "  [bold]brainpalace dashboard start[/]"
            )
        else:
            console.print("[red]Upgrade failed.[/] See the output above.")
        raise SystemExit(result.returncode)

    console.print("\n[green]Upgrade complete.[/]")

    if not servers and not dashboard_live:
        return

    console.print("[bold]Restarting instances…[/]")
    ok = _restart_and_verify(servers, dashboard=dashboard_live, argv=bp, home=home)
    if ok:
        console.print("[green]Restart complete — all instances healthy.[/]")
    else:
        console.print(
            "[red bold]Some instances did not come back.[/] Check the ✗ lines "
            "above and retry with [bold]brainpalace start[/]."
        )
        raise SystemExit(1)
