"""`brainpalace init` --git-history flag + interactive git-history prompt."""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands import init as initmod
from brainpalace_cli.commands.init import init_command

# Deterministic merged config the review grid reads on a FRESH init. Billable
# opt-ins (sessions, git) are OFF so a plain grid accept never enables spend,
# independent of the developer's real global config. Used to re-drive the
# interactive init tests through the grid (Task 5).
_CLEAN_MERGED: dict = {
    "embedding": {"provider": "openai", "model": "text-embedding-3-large"},
    "summarization": {"provider": "openai", "model": "gpt-5-mini"},
    "session_indexing": {"enabled": False, "archive": {"enabled": True}},
    "git_indexing": {"enabled": False},
    "extraction": {"mode": "off"},
    "reranker": {"enabled": False},
    "graphrag": {"enabled": True},
}


def _patch_grid_preview(monkeypatch):
    """Pin the grid's fresh-init preview to a clean, deterministic merged config."""
    monkeypatch.setattr(
        initmod, "_preview_embedding", lambda root: ("openai", "text-embedding-3-large")
    )
    monkeypatch.setattr(
        initmod, "_preview_merged_config", lambda root: dict(_CLEAN_MERGED)
    )


def test_init_existing_brainpalace_offers_delete_or_cancel(tmp_path, monkeypatch):
    """A pre-existing .brainpalace triggers delete/keep/cancel; cancel preserves it.
    The pre-existing check now uses config.yaml (not config.json)."""
    proj = tmp_path / "proj"
    (proj / ".brainpalace").mkdir(parents=True)
    # Simulate an already-initialized project via config.yaml (the new sentinel)
    (proj / ".brainpalace" / "config.yaml").write_text(
        "embedding:\n  provider: openai\n"
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # User answers "cancel" to the delete/keep/cancel prompt.
    result = CliRunner().invoke(
        init_command, ["--path", str(proj), "--no-start"], input="cancel\n"
    )
    assert "already exists" in result.output.lower()
    # Cancel must NOT delete the pre-existing dir.
    assert (proj / ".brainpalace" / "config.yaml").exists()


def test_init_cancel_after_estimate_removes_created_brainpalace(tmp_path, monkeypatch):
    """Cancelling at the up-front estimate rolls back the .brainpalace we created."""
    proj = tmp_path / "fresh"
    proj.mkdir()
    (proj / "a.py").write_text("x = 1\n")
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # Index-target picker first (folder=., type=both), then per-capability prompts
    # suppressed by flags ⇒ reranker gate (n = keep inherited), lemma (n), compute
    # (y), then the estimate gate (y = run it), then the estimate menu (6 = cancel).
    # Estimate cancel ⇒ rollback before Proceed.
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
        input=".\nboth\nn\nn\nc\ny\n6\n",
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
    _patch_grid_preview(monkeypatch)
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: True
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # Accept the grid without touching the Git Indexing division (8) → git stays
    # OFF (resolved default), then Proceed.
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="c\ny\n",
    )
    assert r.exit_code == 0, r.output
    # Grid shown, git division not drilled → no consent warning, no depth prompt,
    # git_indexing not written (resolves OFF for a fresh init).
    assert "[C]ontinue" in r.output
    assert "commits can contain secrets" not in r.output
    assert "How many commits back to index?" not in r.output
    data = yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())
    assert "git_indexing" not in data


def test_init_git_history_prompt_shown_interactively(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    _patch_grid_preview(monkeypatch)
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: True
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # Drill the Git Indexing division (10 in the init grid — BM25=4, GraphRAG=5,
    # Graph Indexing : LSP=6, Compute Query=7, Storage=8, Indexing=9, Git Indexing=10):
    # consent Enabled=Y, depth=0 (unlimited),
    # then Enter past the remaining git fields, [C]ontinue, Proceed=Y.
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="10\ny\n0\n\n\n\n\nc\ny\n",
    )
    assert r.exit_code == 0, r.output
    # Drilling git surfaces the consent warning + the commit-depth follow-up.
    assert "commits can contain secrets" in r.output
    assert "How many commits back to index?" in r.output
    data = yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())
    assert data["git_indexing"]["enabled"] is True
    assert data["git_indexing"]["depth"] == 0


def test_init_git_history_depth_cap_persisted(tmp_path, monkeypatch):
    """A positive commit-cap answer is written to git_indexing.depth."""
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    _patch_grid_preview(monkeypatch)
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: True
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # Drill git (10 in the init grid — Indexing=9, Git Indexing=10):
    # Enabled=Y, depth=500, Enter past the rest, Continue, Proceed.
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="10\ny\n500\n\n\n\n\nc\ny\n",
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())
    assert data["git_indexing"]["depth"] == 500


# ---------------------------------------------------------------------------
# Task 7 — write_extraction_config
# ---------------------------------------------------------------------------


def test_write_extraction_config_sparse(tmp_path):
    from brainpalace_cli.commands.init import write_extraction_config

    write_extraction_config(tmp_path, "subagent")
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert data["extraction"]["mode"] == "subagent"


def test_write_extraction_config_sparse_only_mode(tmp_path):
    """Only the `extraction.mode` key is written — nothing else."""
    from brainpalace_cli.commands.init import write_extraction_config

    write_extraction_config(tmp_path, "provider")
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert set(data["extraction"].keys()) == {"mode"}


def test_write_extraction_config_merges_existing(tmp_path):
    """write_extraction_config deep-merges into an existing config.yaml."""
    (tmp_path / "config.yaml").write_text(
        "embedding:\n  provider: openai\n", encoding="utf-8"
    )
    from brainpalace_cli.commands.init import write_extraction_config

    write_extraction_config(tmp_path, "subagent")
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert data["embedding"]["provider"] == "openai"
    assert data["extraction"]["mode"] == "subagent"


def _existing_simple_project(tmp_path):
    """Write an already-initialized project whose graph store is 'simple'.
    The preexisting check now uses config.yaml (not config.json) as sentinel."""
    sd = tmp_path / ".brainpalace"
    sd.mkdir(parents=True)
    # config.yaml is the sentinel for a pre-existing init (config.json is retired).
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
    # Pre-existing .brainpalace ⇒ keep/delete/cancel first (keep). Then: the review
    # grid (accept with [C]ontinue), the upgrade-store prompt (Y), the Proceed gate
    # (Y), and the re-init editor grid (accept with [C]ontinue).
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="keep\nc\ny\ny\nc\n",
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
        "extraction:\n  mode: subagent\n"
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
    # Turn the pre-existing session features OFF through the grid:
    #   keep
    #   grid1: drill 13 (Extraction Engine) → mode=off, Enter past 10 advanced fields;
    #          drill 11 (Chat Session : Vector Indexing) → Enabled (consent) → N, then
    #            Enter past the 6 remaining session fields (the drill asks all fields;
    #            the gate only collapses the overview). Archive is a separate division.
    #          [C]ontinue
    #   Start gate=Y
    #   grid2 (re-init editor): [C]ontinue
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path)],
        input="keep\n13\noff\n" + "\n" * 10 + "11\nn\n" + "\n" * 6 + "c\ny\nc\n",
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data["extraction"]["mode"] == "off"
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
    # Pre-existing .brainpalace ⇒ keep first. Then:
    #   grid1: drill 10 (Git Indexing — Indexing=9, Git Indexing=10) → Enabled=Y,
    #          depth=0, Enter past the rest, [C]ontinue
    #   upgrade-store=N, Proceed=Y
    #   grid2 (re-init editor): [C]ontinue
    r = CliRunner().invoke(
        init_command,
        ["--path", str(tmp_path), "--no-start"],
        input="keep\n10\ny\n0\n\n\n\n\nc\nn\ny\nc\n",
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data["git_indexing"]["enabled"] is True


def test_no_config_json_written_by_init(tmp_path):
    """init no longer writes config.json — bind lives in config.yaml bind: block.
    Neither DEFAULT_CONFIG nor a config.json file should exist after import."""
    import importlib

    init_mod = importlib.import_module("brainpalace_cli.commands.init")
    assert not hasattr(
        init_mod, "DEFAULT_CONFIG"
    ), "DEFAULT_CONFIG was re-added; bind must live in config.yaml bind: block"
    # A fresh state dir must have no config.json
    state = tmp_path / ".brainpalace"
    state.mkdir()
    assert not (state / "config.json").exists()
