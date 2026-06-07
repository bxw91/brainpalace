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
    # summarize=Y, embed=N, git-history=Y, depth=0 (unlimited), proceed=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="y\nn\ny\n0\ny\n",
    )
    assert r.exit_code == 0, r.output
    assert "Index git commit history?" in r.output
    assert "How many commits back to index?" in r.output
    data = yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())
    assert data["git_indexing"]["enabled"] is True
    assert data["git_indexing"]["depth"] == 0


def test_init_git_history_depth_cap_persisted(tmp_path, monkeypatch):
    """A positive commit-cap answer is written to git_indexing.depth."""
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: True
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # summarize=Y, embed=N, git-history=Y, depth=500, proceed=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="y\nn\ny\n500\ny\n",
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())
    assert data["git_indexing"]["depth"] == 500


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
    # Prompt order: summarize, embed, git-history, upgrade-store, Proceed.
    # summarize=Y, embed=N, git-history=N, upgrade-store=Y, proceed=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="y\nn\nn\ny\ny\n",
    )
    assert r.exit_code == 0, r.output
    assert "Upgrade graph store to sqlite?" in r.output
    # Upgrade is now shown in the "init will:" preview before Proceed.
    assert "upgrade graph store" in r.output.lower()
    assert _store_type(sd) == "sqlite"


def _existing_sqlite_project(tmp_path):
    """An already-initialized project on sqlite with sessions+summarize ON."""
    sd = tmp_path / ".brainpalace"
    sd.mkdir(parents=True)
    (sd / "config.json").write_text(f'{{"project_root": "{tmp_path}"}}')
    (sd / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
        "graphrag:\n  enabled: true\n  store_type: sqlite\n"
        "session_extraction:\n  mode: subagent\n"
        "session_indexing:\n  enabled: true\n"
    )
    return sd


def test_init_reinit_honors_no_summarize_no_embed(tmp_path, monkeypatch):
    """Re-init: answering N to summarize+embed must turn them off (regression).

    The existing-project branch used to ignore the interactive answers and the
    banner read session_extraction from config.json (always absent → defaulted
    to 'subagent'), wrongly reporting 'configured (subagent)'.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: False
    )
    # Avoid real server start + touching ~/.claude hooks; keep the config writes.
    monkeypatch.setattr(
        "brainpalace_cli.commands.init._start_and_watch", lambda **k: []
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.install_session_hooks", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.init._prune_old_extraction_hooks",
        lambda *a, **k: None,
    )
    sd = _existing_sqlite_project(tmp_path)
    # store=sqlite ⇒ no upgrade prompt. summarize=N, embed=N, git=N, proceed=Y.
    r = CliRunner().invoke(
        init_command, ["--path", str(tmp_path)], input="n\nn\nn\ny\n"
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data["session_extraction"]["mode"] == "off"
    assert data["session_indexing"]["enabled"] is False
    assert "configured (subagent)" not in r.output


def test_init_existing_project_git_history_flag_persists(tmp_path, monkeypatch):
    """Re-init on an existing project must persist --git-history (regression)."""
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: False)
    sd = _existing_simple_project(tmp_path)
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start", "--git-history", "--json"],
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data["git_indexing"]["enabled"] is True


def test_init_existing_project_git_history_prompt_persists(tmp_path, monkeypatch):
    """An interactive 'yes' to the git-history prompt persists on a re-init."""
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: True
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    sd = _existing_simple_project(tmp_path)
    # Prompt order: summarize, embed, git-history, depth, upgrade-store, Proceed.
    # summarize=Y, embed=N, git-history=Y, depth=0, upgrade-store=N, proceed=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="y\nn\ny\n0\nn\ny\n",
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data["git_indexing"]["enabled"] is True
