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
    """Return the upgrade command for a given install manager."""
    if manager == "pipx":
        return ["pipx", "upgrade", "brainpalace-cli"]
    if manager == "uv":
        return ["uv", "tool", "upgrade", "brainpalace-cli"]
    if manager == "pip":
        return [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
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


def _preflight_notice() -> None:
    """Warn, before the upgrade runs, what's live and will be bounced after.

    Front-loads the disclosure so the user knows the upgrade touches running
    instances; the actual restart still happens *after* the upgrade (stopping
    them first would kill the dashboard the user may be reading and serves no
    purpose). Silent when nothing is running.
    """
    servers, dash = _running_instances()
    if not servers and not dash:
        return
    parts: list[str] = []
    if servers:
        plural = "s" if len(servers) != 1 else ""
        parts.append(f"{len(servers)} running server{plural}")
    if dash:
        parts.append("the control-plane dashboard")
    what = " and ".join(parts)
    console.print(
        f"[yellow]Heads up:[/] {what} currently running — they keep serving the "
        "OLD code until restarted. You'll be offered a restart right after the "
        "upgrade (or use --no-restart to do it yourself later)."
    )


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


def _restart_after_upgrade(*, assume_yes: bool) -> None:
    """Restart running per-project servers + the dashboard so they load new code.

    Prompts (default yes) when not ``assume_yes``. Each project server is
    restarted with ``--no-dashboard`` so the dashboard is bounced exactly once,
    at the end. Best-effort: a single failure is reported but doesn't abort the
    rest.
    """
    servers = running_servers()
    dash = dashboard_running()
    if not servers and not dash:
        return

    parts: list[str] = []
    if servers:
        plural = "s" if len(servers) != 1 else ""
        parts.append(f"{len(servers)} running server{plural}")
    if dash:
        parts.append("the dashboard")
    what = " and ".join(parts)

    if not assume_yes and not click.confirm(
        f"Restart {what} to load the new version?", default=True
    ):
        console.print(
            "[dim]Skipped. Restart later: "
            "[bold]brainpalace stop && brainpalace start[/].[/]"
        )
        return

    argv = _brainpalace_argv()
    home = str(Path.home())

    def _run(cmd: list[str], label: str) -> None:
        res = subprocess.run(cmd, cwd=home, capture_output=True, text=True)
        if res.returncode != 0:
            console.print(f"  [yellow]![/] {label} failed: {res.stderr.strip()}")

    for project_root in servers:
        console.print(f"[dim]Restarting server:[/] {project_root}")
        _run([*argv, "stop", "--path", project_root, "--json"], "stop")
        _run(
            [*argv, "start", "--path", project_root, "--no-dashboard", "--json"],
            "start",
        )

    if dash:
        console.print("[dim]Restarting dashboard…[/]")
        _run([*argv, "dashboard", "stop"], "dashboard stop")
        # Use --json to capture the base_url, then render the standard panel so
        # `update` shows the dashboard URL box just like `start`/`dashboard start`.
        res = subprocess.run(
            [*argv, "dashboard", "start", "--no-open", "--json"],
            cwd=home,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            console.print(
                f"  [yellow]![/] dashboard start failed: {res.stderr.strip()}"
            )
        else:
            from brainpalace_cli.commands._dashboard_url import render_dashboard_url

            try:
                data = json.loads(res.stdout or "{}")
            except ValueError:
                data = {}
            render_dashboard_url(
                {"base_url": data.get("base_url"), "started": True},
                console=console,
            )

    console.print("[green]Restart complete.[/]")


@click.command("update")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option(
    "--no-restart",
    is_flag=True,
    help="Don't restart running servers/dashboard after the upgrade",
)
def update_command(yes: bool, no_restart: bool) -> None:
    """Upgrade BrainPalace (CLI + server) to the latest published version.

    Auto-detects pipx / uv / pip and runs the matching upgrade. Before running
    it, warns which servers/dashboard are live (they keep serving old code until
    restarted); after it finishes, offers to restart any running per-project
    servers and the dashboard so they load the new code (skip with --no-restart).
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

    _preflight_notice()

    if not yes and not click.confirm("Upgrade now?", default=True):
        console.print("[dim]Aborted.[/]")
        return

    # Run from $HOME so pipx doesn't mistake 'brainpalace-cli' for a local path
    # when the cwd happens to contain a matching subdirectory.
    result = subprocess.run(argv, cwd=str(Path.home()))
    if result.returncode != 0:
        console.print("[red]Upgrade failed.[/] See the output above.")
        raise SystemExit(result.returncode)

    console.print("\n[green]Upgrade complete.[/]")

    if no_restart:
        console.print(
            "[dim]Restart running servers to load the new version: "
            "[bold]brainpalace stop && brainpalace start[/].[/]"
        )
        return
    _restart_after_upgrade(assume_yes=yes)
