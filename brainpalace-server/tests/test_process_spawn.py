"""Guard tests for :mod:`brainpalace_server.process_spawn` (D6/D7/D8).

Pins the posix_spawn preconditions (CPython 3.12 ``Popen._execute_child``):
dir-qualified argv[0], ``close_fds=False``, no ``cwd``, no
``start_new_session``. A regression here silently reintroduces the
fork+exec deadlock hazard this module exists to remove.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from brainpalace_server import process_spawn


def test_resolve_executable_returns_dir_qualified_path():
    resolved = process_spawn.resolve_executable("git")
    assert "/" in resolved or "\\" in resolved


def test_resolve_executable_raises_on_missing_binary():
    with pytest.raises(FileNotFoundError):
        process_spawn.resolve_executable("definitely-not-a-real-binary-xyz")


def test_run_capture_never_falls_back_to_bare_name():
    # A bare-name executable must raise, never silently spawn via fork+exec.
    with pytest.raises(FileNotFoundError):
        process_spawn.run_capture(["definitely-not-a-real-binary-xyz", "--version"])


def test_spawn_stdio_never_falls_back_to_bare_name():
    with pytest.raises(FileNotFoundError):
        process_spawn.spawn_stdio(["definitely-not-a-real-binary-xyz"])


def test_run_capture_satisfies_posix_spawn_preconditions(monkeypatch):
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    process_spawn.run_capture(["git", "--version"])

    argv = captured["argv"]
    kwargs = captured["kwargs"]
    assert "/" in argv[0] or "\\" in argv[0]  # dir-qualified
    assert kwargs["close_fds"] is False
    assert "cwd" not in kwargs
    assert "start_new_session" not in kwargs
    assert "pass_fds" not in kwargs


def test_spawn_stdio_satisfies_posix_spawn_preconditions(monkeypatch):
    captured: dict = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs

        class _FakeProc:
            pass

        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    process_spawn.spawn_stdio(["git"])

    argv = captured["argv"]
    kwargs = captured["kwargs"]
    assert "/" in argv[0] or "\\" in argv[0]  # dir-qualified
    assert kwargs["close_fds"] is False
    assert "cwd" not in kwargs
    assert "start_new_session" not in kwargs
    assert "pass_fds" not in kwargs
    assert kwargs["stdin"] == subprocess.PIPE
    assert kwargs["stdout"] == subprocess.PIPE
    assert kwargs["stderr"] == subprocess.DEVNULL


def test_no_raw_subprocess_spawn_outside_process_spawn_module():
    # Guard (D8): the posix_spawn precondition list in process_spawn.py is
    # invisible at a call site — a bare `subprocess.run(`/`subprocess.Popen(`
    # dropped anywhere else in the package silently reintroduces the
    # fork+exec deadlock hazard (D6). Every server-side spawn must go through
    # this module.
    server_pkg = Path(process_spawn.__file__).resolve().parent
    hits: list[str] = []
    for pattern in ("subprocess.run(", "subprocess.Popen("):
        result = subprocess.run(
            ["grep", "-rn", pattern, str(server_pkg)],
            capture_output=True,
            text=True,
        )
        hits.extend(
            line
            for line in result.stdout.strip().splitlines()
            if line and "process_spawn.py:" not in line
        )
    assert not hits, f"raw subprocess spawn outside process_spawn.py: {hits}"
