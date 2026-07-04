"""`brainpalace lsp install` — CLI surface over `lsp_install.ensure_server`."""

from click.testing import CliRunner

from brainpalace_cli.cli import cli
from brainpalace_cli.lsp_install import EnsureResult


def test_lsp_install_yes_success(monkeypatch):
    import brainpalace_cli.commands.lsp as cmd

    monkeypatch.setattr(cmd, "ensure_server", lambda lang, **k: EnsureResult.INSTALLED)
    r = CliRunner().invoke(cli, ["lsp", "install", "--yes"])
    assert r.exit_code == 0, r.output


def test_lsp_install_already_present(monkeypatch):
    import brainpalace_cli.commands.lsp as cmd

    monkeypatch.setattr(
        cmd, "ensure_server", lambda lang, **k: EnsureResult.ALREADY_PRESENT
    )
    r = CliRunner().invoke(cli, ["lsp", "install", "--yes"])
    assert r.exit_code == 0
    assert "already" in r.output.lower()


def test_lsp_install_failed_exit_nonzero(monkeypatch):
    import brainpalace_cli.commands.lsp as cmd

    monkeypatch.setattr(cmd, "ensure_server", lambda lang, **k: EnsureResult.FAILED)
    r = CliRunner().invoke(cli, ["lsp", "install", "--yes"])
    assert r.exit_code == 1


def test_lsp_install_no_manager_exit_nonzero(monkeypatch):
    import brainpalace_cli.commands.lsp as cmd

    monkeypatch.setattr(cmd, "ensure_server", lambda lang, **k: EnsureResult.NO_MANAGER)
    r = CliRunner().invoke(cli, ["lsp", "install", "--yes"])
    assert r.exit_code == 1


def test_lsp_install_not_on_path_is_success(monkeypatch):
    # Installed-but-not-on-PATH is a successful install (exit 0), not a failure.
    import brainpalace_cli.commands.lsp as cmd

    monkeypatch.setattr(
        cmd, "ensure_server", lambda lang, **k: EnsureResult.INSTALLED_NOT_ON_PATH
    )
    r = CliRunner().invoke(cli, ["lsp", "install", "--yes"])
    assert r.exit_code == 0
