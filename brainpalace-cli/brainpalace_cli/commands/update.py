"""Update command — upgrade BrainPalace to the latest published version.

Detects how the CLI was installed (pipx / uv / pip) and runs the matching
upgrade. The published wheels carry the correct version straight from
``pyproject.toml``; a restart of any running server is needed for the new
code to take effect.
"""

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
    p = str(bin_path)
    if "/pipx/" in p:
        return "pipx"
    if "/uv/tools/" in p:
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


@click.command("update")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def update_command(yes: bool) -> None:
    """Upgrade BrainPalace (CLI + server) to the latest published version.

    Auto-detects pipx / uv / pip and runs the matching upgrade. After it
    finishes, restart any running server so it picks up the new code.
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
    console.print(
        "[yellow]Restart[/] any running server to load the new version: "
        "[bold]brainpalace stop && brainpalace start[/]"
    )
