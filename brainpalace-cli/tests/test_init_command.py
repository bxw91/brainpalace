"""`brainpalace init` --git-history flag + interactive git-history prompt."""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands.init import init_command


def test_init_git_history_flag_writes_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: False)
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start", "--git-history", "--json"],
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())
    assert data["git_indexing"]["enabled"] is True


def test_init_default_no_git_history(tmp_path, monkeypatch):
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: False)
    r = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--no-start", "--json"]
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())
    assert "git_indexing" not in data  # default off = not written


def test_init_git_history_prompt_shown_interactively(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: True
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # summarize=Y, embed=N, git-history=Y, proceed=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="y\nn\ny\ny\n",
    )
    assert r.exit_code == 0, r.output
    assert "Index git commit history?" in r.output
    data = yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())
    assert data["git_indexing"]["enabled"] is True


def _existing_simple_project(tmp_path):
    """Write an already-initialized project whose graph store is 'simple'."""
    sd = tmp_path / ".brainpalace"
    sd.mkdir(parents=True)
    (sd / "config.json").write_text(f'{{"project_root": "{tmp_path}"}}')
    (sd / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
        "graphrag:\n  enabled: true\n  store_type: simple\n  use_code_metadata: true\n"
    )
    return sd


def _store_type(sd) -> str:
    return yaml.safe_load((sd / "config.yaml").read_text())["graphrag"]["store_type"]


def test_init_migrate_graph_store_flag_upgrades(tmp_path, monkeypatch):
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: False)
    sd = _existing_simple_project(tmp_path)
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start", "--migrate-graph-store", "--json"],
    )
    assert r.exit_code == 0, r.output
    assert _store_type(sd) == "sqlite"
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data["embedding"]["provider"] == "openai"  # other config preserved


def test_init_no_migrate_keeps_simple(tmp_path, monkeypatch):
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: False)
    sd = _existing_simple_project(tmp_path)
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start", "--no-migrate-graph-store", "--json"],
    )
    assert r.exit_code == 0, r.output
    assert _store_type(sd) == "simple"


def test_init_noninteractive_no_flag_keeps_simple(tmp_path, monkeypatch):
    """Conservative: a bare non-interactive re-init never silently migrates data."""
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: False)
    sd = _existing_simple_project(tmp_path)
    r = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--no-start", "--json"]
    )
    assert r.exit_code == 0, r.output
    assert _store_type(sd) == "simple"


def test_init_migrate_prompt_shown_interactively(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: True
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    sd = _existing_simple_project(tmp_path)
    # summarize=Y, embed=N, git-history=N, proceed=Y, upgrade-store=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="y\nn\nn\ny\ny\n",
    )
    assert r.exit_code == 0, r.output
    assert "Upgrade graph store to sqlite?" in r.output
    assert _store_type(sd) == "sqlite"
