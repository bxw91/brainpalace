"""`brainpalace init` --git-history flag + interactive git-history prompt."""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands.init import init_command


def test_init_existing_brainpalace_offers_delete_or_cancel(tmp_path, monkeypatch):
    """A pre-existing .brainpalace triggers delete/keep/cancel; cancel preserves it."""
    proj = tmp_path / "proj"
    (proj / ".brainpalace").mkdir(parents=True)
    (proj / ".brainpalace" / "config.json").write_text("{}")
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # User answers "cancel" to the delete/keep/cancel prompt.
    result = CliRunner().invoke(
        init_command, ["--path", str(proj), "--no-start"], input="cancel\n"
    )
    assert "already exists" in result.output.lower()
    # Cancel must NOT delete the pre-existing dir.
    assert (proj / ".brainpalace" / "config.json").exists()


def test_init_cancel_after_estimate_removes_created_brainpalace(tmp_path, monkeypatch):
    """Cancelling at the up-front estimate rolls back the .brainpalace we created."""
    proj = tmp_path / "fresh"
    proj.mkdir()
    (proj / "a.py").write_text("x = 1\n")
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # Per-capability prompts suppressed by flags ⇒ reranker gate (n = keep
    # inherited), lemma (n), then the estimate gate (y = run it), then the estimate
    # prompt (cancel). Estimate cancel ⇒ rollback before the final Proceed.
    result = CliRunner().invoke(
        init_command,
        [
            "--path",
            str(proj),
            "--no-git-history",
            "--no-sessions",
            "--no-extract",
            "--no-graphrag-extract",
            "--no-archive",
        ],
        input="n\nn\ny\ncancel\n",
    )
    assert result.exit_code == 0, result.output
    assert not (proj / ".brainpalace").exists()


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


def test_init_git_history_prompt_defaults_off_with_no_global(tmp_path, monkeypatch):
    """Fresh interactive init (no global config) pre-selects NO for git history.

    Parity with the wizard + server schema, which both default git indexing OFF
    (commit diffs can carry secrets). Pressing enter at the git prompt must keep
    it off, so git_indexing is never written. Regression for the `_global_default`
    fallback that was wrongly True.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: True
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # summarize=N, embed=N, archive=enter(Y), git-history=enter(default),
    # graphrag-extract=N, reranker-change=N, lemma=N, proceed=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="n\nn\n\n\nn\nn\nn\ny\n",
    )
    assert r.exit_code == 0, r.output
    assert "Index git commit history?" in r.output
    # default declined → no depth prompt, git_indexing not written (inherits off)
    assert "How many commits back to index?" not in r.output
    data = yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())
    assert "git_indexing" not in data


def test_init_git_history_prompt_shown_interactively(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: True
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # summarize=Y, embed=N, archive=Y, git-history=Y, depth=0 (unlimited),
    # graphrag-extract=N, reranker-change=N, lemma=N, proceed=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="y\nn\ny\ny\n0\nn\nn\nn\ny\n",
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
    # summarize=Y, embed=N, archive=Y, git-history=Y, depth=500,
    # graphrag-extract=N, reranker-change=N, lemma=N, proceed=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="y\nn\ny\ny\n500\nn\nn\nn\ny\n",
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
    # Pre-existing .brainpalace ⇒ keep/delete/cancel first (keep), then prompt
    # order: summarize, embed, archive, git-history, graphrag-extract,
    # reranker-change, lemma, upgrade-store, Proceed.
    # keep, summarize=Y, embed=N, archive=Y, git-history=N, graphrag-extract=N,
    # reranker-change=N, lemma=N, upgrade-store=Y, proceed=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="keep\ny\nn\ny\nn\nn\nn\nn\ny\ny\n",
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
    # Pre-existing .brainpalace ⇒ keep first. store=sqlite ⇒ no upgrade prompt.
    # keep, summarize=N, embed=N, archive=N, git=N, graphrag-extract=N,
    # reranker-change=N, lemma=N, proceed=Y.
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path)],
        input="keep\nn\nn\nn\nn\nn\nn\nn\ny\n",
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
    # Pre-existing .brainpalace ⇒ keep first. Prompt order: summarize, embed,
    # archive, git-history, depth, graphrag-extract, reranker-change, lemma,
    # upgrade-store, Proceed.
    # keep, summarize=Y, embed=N, archive=Y, git-history=Y, depth=0,
    # graphrag-extract=N, reranker-change=N, lemma=N, upgrade-store=N, proceed=Y
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="keep\ny\nn\ny\ny\n0\nn\nn\nn\nn\ny\n",
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data["git_indexing"]["enabled"] is True
