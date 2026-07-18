"""Single seam for every server-side child-process spawn.

CPython's ``subprocess.Popen`` only takes the ``posix_spawn`` fast path when
the executable is dir-qualified, ``close_fds=False``, no ``pass_fds``,
``cwd is None``, and ``start_new_session`` is false (verified against CPython
3.12's ``Popen._execute_child``). Any other combination — including the
default ``close_fds=True`` with a bare executable name like ``"git"`` — falls
back to ``fork()`` + ``exec()``.

That fallback is a hazard here: the server spawns ``git`` (and LSP servers)
from ``asyncio.to_thread`` worker threads. A child forked while another
thread holds an allocator/glibc lock can deadlock before it ever reaches
``exec``, leaving behind a zombie clone that inherits (and pins) the
server's listening socket forever.

``posix_spawn``'s ``vfork``/``CLONE_VM|CLONE_VFORK`` implementation has no
such Python-level child and therefore no lock-inheritance deadlock. Routing
every spawn through this module — instead of six ad hoc call sites — is what
keeps the precondition list from silently rotting the next time someone adds
a ``cwd=`` or a bare executable name.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

__all__ = ["resolve_executable", "run_capture", "spawn_stdio"]


def resolve_executable(name: str) -> str:
    """Resolve ``name`` to a dir-qualified path via ``shutil.which``.

    Raises ``FileNotFoundError`` rather than silently handing subprocess a
    bare name — a bare name forces the fork+exec path this module exists to
    avoid.
    """
    resolved = shutil.which(name)
    if resolved is None:
        raise FileNotFoundError(f"executable not found on PATH: {name!r}")
    return resolved


def _resolved_argv(argv: list[str]) -> list[str]:
    if not argv:
        raise ValueError("argv must be non-empty")
    return [resolve_executable(argv[0]), *argv[1:]]


def _assert_posix_spawn_preconditions(argv: list[str]) -> None:
    """Guard D6: argv[0] must be dir-qualified or ``posix_spawn`` won't be used."""
    exe = argv[0]
    if os.sep not in exe and (os.altsep is None or os.altsep not in exe):
        raise ValueError(
            f"process_spawn requires a resolved (dir-qualified) argv[0], got {exe!r}"
        )


def run_capture(
    argv: list[str],
    *,
    timeout: float | None = None,
    check: bool = False,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    """``subprocess.run`` with output captured, routed via ``posix_spawn``."""
    resolved = _resolved_argv(argv)
    _assert_posix_spawn_preconditions(resolved)
    return subprocess.run(
        resolved,
        capture_output=True,
        text=text,
        timeout=timeout,
        check=check,
        close_fds=False,
    )


def spawn_stdio(argv: list[str]) -> subprocess.Popen[bytes]:
    """``subprocess.Popen`` wired for LSP stdio (PIPE/PIPE/DEVNULL)."""
    resolved = _resolved_argv(argv)
    _assert_posix_spawn_preconditions(resolved)
    return subprocess.Popen(
        resolved,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        close_fds=False,
    )
