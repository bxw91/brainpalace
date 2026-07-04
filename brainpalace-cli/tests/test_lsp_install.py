import subprocess
from unittest.mock import MagicMock

from brainpalace_cli import lsp_install as li
from brainpalace_cli.lsp_install import EnsureResult, Installer


def _abs(manager):
    return f"/usr/bin/{manager}"


def test_resolve_prefers_pipx_and_uses_absolute_path(monkeypatch):
    monkeypatch.setattr(li.shutil, "which", lambda n: _abs(n) if n == "pipx" else None)
    inst = li.resolve_installer("python")
    assert inst is not None and inst.manager == "pipx"
    # argv[0] rewritten to the resolved absolute path (H3):
    assert inst.argv == ["/usr/bin/pipx", "install", "pyright"]


def test_resolve_falls_back_to_npm_absolute(monkeypatch):
    monkeypatch.setattr(li.shutil, "which", lambda n: _abs(n) if n == "npm" else None)
    inst = li.resolve_installer("python")
    assert inst is not None and inst.manager == "npm"
    assert inst.argv[0] == "/usr/bin/npm"


def test_pip_only_inside_venv(monkeypatch):
    # No pipx/npm; pip must be gated on an active venv.
    monkeypatch.setattr(li.shutil, "which", lambda n: None)
    monkeypatch.setattr(li, "_in_venv", lambda: False)
    assert li.resolve_installer("python") is None
    monkeypatch.setattr(li, "_in_venv", lambda: True)
    inst = li.resolve_installer("python")
    assert inst is not None and inst.manager == "pip"
    assert inst.argv[0] == li.sys.executable  # already absolute


def test_ensure_already_present_noop(monkeypatch):
    monkeypatch.setattr(li, "server_present", lambda lang: True)
    run = MagicMock()
    monkeypatch.setattr(li.subprocess, "run", run)
    assert (
        li.ensure_server("python", assume_yes=True, interactive=False)
        == EnsureResult.ALREADY_PRESENT
    )
    run.assert_not_called()


def test_ensure_no_manager(monkeypatch):
    monkeypatch.setattr(li, "server_present", lambda lang: False)
    monkeypatch.setattr(li, "resolve_installer", lambda lang: None)
    assert (
        li.ensure_server("python", assume_yes=True, interactive=False)
        == EnsureResult.NO_MANAGER
    )


def test_ensure_declined_when_not_interactive_and_no_yes(monkeypatch):
    monkeypatch.setattr(li, "server_present", lambda lang: False)
    monkeypatch.setattr(
        li,
        "resolve_installer",
        lambda lang: Installer("pipx", ["/usr/bin/pipx", "install", "pyright"]),
    )
    assert (
        li.ensure_server("python", assume_yes=False, interactive=False)
        == EnsureResult.DECLINED
    )


def test_ensure_prompt_defaults_to_no(monkeypatch):
    # H5: with no --yes, an interactive prompt whose default is taken (No) declines.
    monkeypatch.setattr(li, "server_present", lambda lang: False)
    monkeypatch.setattr(
        li,
        "resolve_installer",
        lambda lang: Installer("pipx", ["/usr/bin/pipx", "install", "pyright"]),
    )
    seen = {}

    def _confirm(msg, default=False):
        seen["default"] = default
        return default  # user presses Enter

    monkeypatch.setattr(li.click, "confirm", _confirm)
    assert (
        li.ensure_server("python", assume_yes=False, interactive=True)
        == EnsureResult.DECLINED
    )
    assert seen["default"] is False


def test_ensure_installs_and_reverifies_on_path(monkeypatch):
    calls = {"present": [False, True]}  # missing before, present (on PATH) after
    monkeypatch.setattr(li, "server_present", lambda lang: calls["present"].pop(0))
    monkeypatch.setattr(
        li,
        "resolve_installer",
        lambda lang: Installer("pipx", ["/usr/bin/pipx", "install", "pyright"]),
    )
    proc = MagicMock(returncode=0, stdout="ok", stderr="")
    run = MagicMock(return_value=proc)
    monkeypatch.setattr(li.subprocess, "run", run)
    assert (
        li.ensure_server("python", assume_yes=True, interactive=False)
        == EnsureResult.INSTALLED
    )
    # H1: install ran with a timeout.
    assert run.call_args.kwargs.get("timeout") == li.INSTALL_TIMEOUT


def test_ensure_installed_not_on_path(monkeypatch):
    # H2: binary landed in the manager's bin dir but is not on PATH.
    monkeypatch.setattr(li, "server_present", lambda lang: False)  # never on PATH
    monkeypatch.setattr(
        li,
        "resolve_installer",
        lambda lang: Installer("pipx", ["/usr/bin/pipx", "install", "pyright"]),
    )
    monkeypatch.setattr(
        li, "_found_in_manager_bindir", lambda lang, inst: "/home/u/.local/bin"
    )
    proc = MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(li.subprocess, "run", lambda *a, **k: proc)
    assert (
        li.ensure_server("python", assume_yes=True, interactive=False)
        == EnsureResult.INSTALLED_NOT_ON_PATH
    )


def test_ensure_failed_when_binary_absent_everywhere(monkeypatch):
    monkeypatch.setattr(li, "server_present", lambda lang: False)
    monkeypatch.setattr(
        li,
        "resolve_installer",
        lambda lang: Installer("pipx", ["/usr/bin/pipx", "install", "pyright"]),
    )
    monkeypatch.setattr(li, "_found_in_manager_bindir", lambda lang, inst: None)
    proc = MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(li.subprocess, "run", lambda *a, **k: proc)
    assert (
        li.ensure_server("python", assume_yes=True, interactive=False)
        == EnsureResult.FAILED
    )


def test_ensure_failed_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(li, "server_present", lambda lang: False)
    monkeypatch.setattr(
        li,
        "resolve_installer",
        lambda lang: Installer("npm", ["/usr/bin/npm", "i", "-g", "pyright"]),
    )
    proc = MagicMock(returncode=1, stdout="", stderr="EACCES")
    monkeypatch.setattr(li.subprocess, "run", lambda *a, **k: proc)
    assert (
        li.ensure_server("python", assume_yes=True, interactive=False)
        == EnsureResult.FAILED
    )


def test_ensure_failed_on_timeout(monkeypatch):
    # H1: a hung installer must not hang us.
    monkeypatch.setattr(li, "server_present", lambda lang: False)
    monkeypatch.setattr(
        li,
        "resolve_installer",
        lambda lang: Installer("npm", ["/usr/bin/npm", "i", "-g", "pyright"]),
    )

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="npm", timeout=1)

    monkeypatch.setattr(li.subprocess, "run", _boom)
    assert (
        li.ensure_server("python", assume_yes=True, interactive=False)
        == EnsureResult.FAILED
    )
