"""`brainpalace init` session-memory default + opt-out.

Session memory is ON by default for new projects: it indexes this project's AI
chat transcripts (assistant + tool turns). --sessions and non-interactive runs
write session_indexing.enabled: true into the project config.yaml; an
interactive run confirms with a default of yes. --no-sessions opts out and
leaves the block absent.
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


def test_init_sessions_flag_enables_block(tmp_path, monkeypatch):
    result = _run(["--path", str(tmp_path), "--sessions"], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is True
    # Must not clobber the provider defaults written alongside it.
    assert cfg["embedding"]["provider"] == "openai"


def test_init_no_sessions_leaves_block_absent(tmp_path, monkeypatch):
    result = _run(["--path", str(tmp_path), "--no-sessions"], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    assert "session_indexing" not in _cfg(tmp_path)


def test_init_default_non_interactive_enables_block(tmp_path, monkeypatch):
    # No TTY -> new-project default is ON, block written enabled.
    result = _run(["--path", str(tmp_path)], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    assert _cfg(tmp_path)["session_indexing"]["enabled"] is True


def test_init_json_non_interactive_enables_block(tmp_path, monkeypatch):
    # --json is non-interactive too -> default ON.
    result = _run(["--path", str(tmp_path), "--json"], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    assert _cfg(tmp_path)["session_indexing"]["enabled"] is True
