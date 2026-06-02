"""`brainpalace init` session capabilities: independent archive + index.

For new projects both default ON: init writes session_indexing.enabled: true
(INDEX = embeddings) and session_indexing.archive.enabled: true (ARCHIVE = raw
transcript backup). --no-sessions disables only the index (archive stays on);
--no-archive disables only the archive. Non-interactive runs enable both; an
interactive run confirms the index with a default of yes.
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


def test_init_no_archive_keeps_index_on(tmp_path, monkeypatch):
    # --no-archive disables ARCHIVE only; INDEX stays on (default).
    result = _run(["--path", str(tmp_path), "--no-archive"], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is True
    assert cfg["session_indexing"]["archive"]["enabled"] is False


def test_init_default_non_interactive_enables_both(tmp_path, monkeypatch):
    # No TTY -> new-project default is ON for both capabilities.
    result = _run(["--path", str(tmp_path)], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is True
    assert cfg["session_indexing"]["archive"]["enabled"] is True


def test_init_json_non_interactive_enables_both(tmp_path, monkeypatch):
    # --json is non-interactive too -> default ON for both.
    result = _run(["--path", str(tmp_path), "--json"], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is True
    assert cfg["session_indexing"]["archive"]["enabled"] is True


def test_init_respects_xdg_global_default(tmp_path, monkeypatch):
    # An XDG global config with session_indexing disabled must NOT be clobbered
    # back to ON by init's fresh-project default.
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
    assert cfg["session_indexing"]["enabled"] is False
    assert cfg["session_indexing"]["archive"]["enabled"] is False


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
