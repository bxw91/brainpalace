"""CLI-side language-server installer (Python -> pyright).

The server is headless (no TTY) and may run on a different host, so installing
a language server is a local-machine, consent-gated action that lives here, not
server-side. Server stays detect-only / fail-soft.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum

import click

INSTALL_TIMEOUT = 300  # seconds; a hung installer must not block init/doctor (H1)


@dataclass(frozen=True)
class Installer:
    manager: str
    argv: list[str]  # argv[0] = manager-name template until resolve rewrites it


# Per-language installer registry. Probe order = preference; first available wins.
# pip entries run inside the active venv only (never global system pip).
INSTALLERS: dict[str, list[Installer]] = {
    "python": [
        Installer("pipx", ["pipx", "install", "pyright"]),
        Installer("npm", ["npm", "i", "-g", "pyright"]),
        Installer("pip", [sys.executable, "-m", "pip", "install", "pyright"]),
    ],
}


class EnsureResult(str, Enum):
    ALREADY_PRESENT = "already_present"
    INSTALLED = "installed"
    INSTALLED_NOT_ON_PATH = "installed_not_on_path"
    DECLINED = "declined"
    NO_MANAGER = "no_manager"
    FAILED = "failed"


def _in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _detect_binaries(lang: str) -> tuple[str, ...]:
    """Candidate server binary names, reused from the server's PUBLIC accessor so
    the CLI probe and the server probe cannot drift (H6)."""
    try:
        from brainpalace_server.lsp.servers import detect_binaries
    except Exception:  # noqa: BLE001 — server not importable: fall back
        return {"python": ("pyright-langserver", "pyright")}.get(lang, ())
    names: tuple[str, ...] = tuple(detect_binaries(lang))
    return names


def server_present(lang: str) -> bool:
    return any(shutil.which(name) for name in _detect_binaries(lang))


def resolve_installer(lang: str) -> Installer | None:
    """First available installer, with argv[0] rewritten to the resolved
    ABSOLUTE path (H3: Windows npm.cmd + no PATH-hijack between check and run)."""
    for inst in INSTALLERS.get(lang, []):
        if inst.manager == "pip":
            if _in_venv():  # argv[0] is already sys.executable (absolute)
                return inst
            continue
        path = shutil.which(inst.manager)
        if path:
            return Installer(inst.manager, [path, *inst.argv[1:]])
    return None


def _display_cmd(inst: Installer) -> str:
    if inst.manager == "pip":
        return "pip install pyright"
    return f"{inst.manager} " + " ".join(inst.argv[1:])


def _manager_bindir(inst: Installer) -> str | None:
    """The bin dir a manager installs console scripts into, if we can name it."""
    if inst.manager == "pipx":
        return os.path.join(os.path.expanduser("~"), ".local", "bin")
    if inst.manager == "npm":
        try:
            out = subprocess.run(
                [inst.argv[0], "prefix", "-g"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            prefix = out.stdout.strip()
            return os.path.join(prefix, "bin") if prefix else None
        except Exception:  # noqa: BLE001
            return None
    return None  # pip installs into the active venv, already on PATH


def _found_in_manager_bindir(lang: str, inst: Installer) -> str | None:
    """Return the dir if the server binary exists in the manager's bin dir but
    isn't on PATH (H2). None if not found there."""
    bindir = _manager_bindir(inst)
    if not bindir:
        return None
    for name in _detect_binaries(lang):
        cand = os.path.join(bindir, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return bindir
    return None


def ensure_server(lang: str, *, assume_yes: bool, interactive: bool) -> EnsureResult:
    """Detect the language server; prompt (unless assume_yes) and install if
    missing; re-verify against PATH and the manager's bin dir. Renders its own
    user-facing lines via click.echo."""
    if server_present(lang):
        return EnsureResult.ALREADY_PRESENT

    inst = resolve_installer(lang)
    if inst is None:
        click.echo(
            f"No package manager found to install the {lang} language server "
            f"(pyright). Install pipx or npm, then rerun. "
            f"See docs/LSP_INTEGRATION.md."
        )
        return EnsureResult.NO_MANAGER

    cmd = _display_cmd(inst)
    if not assume_yes:
        if not interactive:
            return EnsureResult.DECLINED
        click.echo(f"Language server for {lang} (pyright) is not installed.")
        if not click.confirm(
            f"Install it now? ({cmd})", default=False
        ):  # H5: default No
            return EnsureResult.DECLINED

    click.echo(f"Installing: {cmd}")
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, absolute argv[0], no shell
            inst.argv, capture_output=True, text=True, timeout=INSTALL_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        click.echo(f"Install timed out after {INSTALL_TIMEOUT}s. Run manually: {cmd}")
        return EnsureResult.FAILED

    if proc.returncode != 0:
        if proc.stdout:
            click.echo(proc.stdout.strip())
        if proc.stderr:
            click.echo(proc.stderr.strip())
        click.echo(f"Install failed. Run it manually: {cmd}")
        return EnsureResult.FAILED

    if server_present(lang):
        click.echo("Installed pyright.")
        return EnsureResult.INSTALLED

    bindir = _found_in_manager_bindir(lang, inst)
    if bindir:
        click.echo(
            f"Installed pyright, but {bindir} is not on your PATH. "
            f"Add it to PATH to enable exact cross-file graph edges."
        )
        return EnsureResult.INSTALLED_NOT_ON_PATH

    click.echo(f"Install ran but pyright is not detectable. Run manually: {cmd}")
    return EnsureResult.FAILED
