"""`brainpalace init` session capabilities: independent archive + index.

ARCHIVE (raw transcript backup, free) defaults ON always. INDEX (embeddings,
billable) follows the all-on rule: ON in an interactive TTY (confirmed) or with
--yes, OFF in non-interactive/--json runs. Explicit --sessions/--no-sessions and
--archive/--no-archive always win. These tests run via CliRunner (no TTY), so
the implicit index default is OFF unless --yes or --sessions is passed.
"""

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands.init import init_command


def _run(args, monkeypatch, tmp_path):
    # Isolate XDG so a real user config.yaml is not copied over the default.
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.get_xdg_config_dir",
        lambda: tmp_path / "xdg",
    )
    # CliRunner has no TTY, so the interactive confirm branch is never taken
    # here; these tests cover the flag + non-interactive default behavior.
    return CliRunner().invoke(init_command, args)


def _cfg(tmp_path):
    return yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())


def test_init_sessions_flag_enables_both(tmp_path, monkeypatch):
    result = _run(["--path", str(tmp_path), "--sessions"], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is True
    assert cfg["session_indexing"]["archive"]["enabled"] is True
    # Must not clobber the provider defaults written alongside it.
    assert cfg["embedding"]["provider"] == "openai"


def test_init_no_sessions_keeps_archive_on(tmp_path, monkeypatch):
    # --no-sessions disables INDEX only; ARCHIVE stays on (independent).
    result = _run(["--path", str(tmp_path), "--no-sessions"], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is False
    assert cfg["session_indexing"]["archive"]["enabled"] is True


def test_init_no_archive_keeps_index_independent(tmp_path, monkeypatch):
    # --no-archive disables ARCHIVE only; --sessions keeps INDEX on (independent).
    result = _run(
        ["--path", str(tmp_path), "--sessions", "--no-archive"], monkeypatch, tmp_path
    )
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is True
    assert cfg["session_indexing"]["archive"]["enabled"] is False


def test_init_default_non_interactive_archive_only(tmp_path, monkeypatch):
    # No TTY, no --yes -> config-only baseline: ARCHIVE on, INDEX off.
    result = _run(["--path", str(tmp_path)], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is False
    assert cfg["session_indexing"]["archive"]["enabled"] is True


def test_init_json_non_interactive_archive_only(tmp_path, monkeypatch):
    # --json is non-interactive -> ARCHIVE on, INDEX off.
    result = _run(["--path", str(tmp_path), "--json"], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is False
    assert cfg["session_indexing"]["archive"]["enabled"] is True


def test_init_respects_xdg_global_default(tmp_path, monkeypatch):
    # An XDG global config with session_indexing disabled must NOT be clobbered
    # back to ON. Under layered resolution (code < global < project) the project
    # INHERITS the global by OMITTING the block — sparse config, no override.
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    (xdg / "config.yaml").write_text(
        "embedding:\n  provider: openai\n"
        "session_indexing:\n  enabled: false\n  archive:\n    enabled: false\n"
    )
    monkeypatch.setattr("brainpalace_cli.commands.init.get_xdg_config_dir", lambda: xdg)
    result = CliRunner().invoke(init_command, ["--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    # No project-level override → the global's disabled values govern at runtime.
    assert "session_indexing" not in cfg


def test_init_flag_overrides_xdg_default(tmp_path, monkeypatch):
    # Explicit --sessions wins over an XDG-disabled global default.
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    (xdg / "config.yaml").write_text(
        "embedding:\n  provider: openai\nsession_indexing:\n  enabled: false\n"
    )
    monkeypatch.setattr("brainpalace_cli.commands.init.get_xdg_config_dir", lambda: xdg)
    result = CliRunner().invoke(init_command, ["--path", str(tmp_path), "--sessions"])
    assert result.exit_code == 0, result.output
    assert _cfg(tmp_path)["session_indexing"]["enabled"] is True


def test_init_yes_keeps_archive_but_embedding_is_opt_in(tmp_path, monkeypatch):
    # --yes is non-interactive consent, but embedding is now OPT-IN: archive stays
    # on, session indexing (embedding) stays OFF unless --sessions is passed.
    # --no-start keeps this config-only so no server subprocess is spawned.
    result = _run(
        ["--path", str(tmp_path), "--yes", "--no-start"], monkeypatch, tmp_path
    )
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is False  # opt-in, not auto-enabled
    assert cfg["session_indexing"]["archive"]["enabled"] is True


def test_embed_prompt_no_wins_over_xdg_enabled_block(tmp_path, monkeypatch):
    # XDG global enables session indexing, but the interactive embed prompt
    # answer (No) is an explicit choice and must win over the inherited default.
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    (xdg / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
        "session_indexing:\n  enabled: true\n"
    )
    monkeypatch.setattr("brainpalace_cli.commands.init.get_xdg_config_dir", lambda: xdg)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: False
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # summarize=n, embed=n, git-history=n, proceed=y  (--no-start ⇒ no server).
    r = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--no-start"], input="n\nn\nn\ny\n"
    )
    assert r.exit_code == 0, r.output
    assert _cfg(tmp_path)["session_indexing"]["enabled"] is False


def test_init_yes_with_sessions_flag_enables_embedding(tmp_path, monkeypatch):
    # Explicit --sessions opts into embedding even non-interactively.
    result = _run(
        ["--path", str(tmp_path), "--yes", "--no-start", "--sessions"],
        monkeypatch,
        tmp_path,
    )
    assert result.exit_code == 0, result.output
    assert _cfg(tmp_path)["session_indexing"]["enabled"] is True


def test_init_interactive_accepting_global_default_inherits(tmp_path, monkeypatch):
    # Global enables git history. Interactive run pre-fills the git prompt with
    # the global default (yes); accepting it must NOT write git_indexing to the
    # project (it inherits from global). Sparse-write: only divergences persist.
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    (xdg / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
        "git_indexing:\n  enabled: true\n"
    )
    monkeypatch.setattr("brainpalace_cli.commands.init.get_xdg_config_dir", lambda: xdg)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **k: False
    )
    # summarize=enter, embed=enter, git=enter(accept global yes), depth=enter, proceed=y
    r = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--no-start"], input="\n\n\n\ny\n"
    )
    assert r.exit_code == 0, r.output
    assert "(default taken from your global config)" in r.output
    cfg = _cfg(tmp_path)
    assert "git_indexing" not in cfg  # accepted global default → inherited
