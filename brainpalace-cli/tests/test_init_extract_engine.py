"""`brainpalace init` writes mode=auto and reconciles Claude Code hooks.

Engine is decided at runtime by plugin presence, so init always writes ``auto``
(``off`` with --no-extract). Hook reconciliation follows plugin presence:

- Plugin present → plugin owns all 3 hooks; init only prunes old extraction
  hooks (does NOT install the reminder — avoids a double SessionStart).
- Plugin absent → init installs the SessionStart reminder (which also prunes).
"""

import json

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands.init import apply_extract_engine, init_command


def _cfg(tmp_path):
    return yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())


def _patch(monkeypatch, tmp_path, *, plugin: bool):
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.get_xdg_config_dir",
        lambda: tmp_path / "xdg",
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed",
        lambda **kw: plugin,
    )
    calls: list = []
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.install_session_hooks",
        lambda home: calls.append(home),
    )
    return calls


def test_init_writes_auto_and_installs_reminder_when_no_plugin(tmp_path, monkeypatch):
    calls = _patch(monkeypatch, tmp_path, plugin=False)
    result = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--yes", "--no-start", "--extract"]
    )
    assert result.exit_code == 0, result.output
    assert _cfg(tmp_path)["session_extraction"]["mode"] == "auto"
    # No plugin → CLI installs the SessionStart reminder.
    assert len(calls) == 1


def test_init_writes_auto_and_skips_reminder_when_plugin(tmp_path, monkeypatch):
    calls = _patch(monkeypatch, tmp_path, plugin=True)
    result = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--yes", "--no-start", "--extract"]
    )
    assert result.exit_code == 0, result.output
    assert _cfg(tmp_path)["session_extraction"]["mode"] == "auto"
    # Plugin owns the reminder → init must NOT install it (no double SessionStart).
    assert calls == []


def test_init_no_extract_writes_off(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path, plugin=False)
    result = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--no-start", "--no-extract"]
    )
    assert result.exit_code == 0, result.output
    assert _cfg(tmp_path)["session_extraction"]["mode"] == "off"


def test_init_prints_auto_note(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path, plugin=False)
    result = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--yes", "--no-start", "--extract"]
    )
    assert result.exit_code == 0, result.output
    assert "auto" in result.output


def _settings_with_old_extraction_hooks(home):
    claude = home / ".claude"
    claude.mkdir(parents=True)
    (claude / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionEnd": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "bash ~/.claude/hooks/"
                                        "brainpalace-sessionend.sh"
                                    ),
                                }
                            ]
                        }
                    ],
                    "UserPromptSubmit": [
                        {"hooks": [{"type": "command", "command": "bash mine.sh"}]}
                    ],
                }
            }
        )
    )
    return claude / "settings.json"


def test_apply_extract_engine_plugin_present_prunes_only(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **kw: True
    )
    home = tmp_path / "home"
    settings_path = _settings_with_old_extraction_hooks(home)
    state = tmp_path / ".brainpalace"
    state.mkdir()

    mode = apply_extract_engine(state, tmp_path, enabled=True, home=home)

    assert mode == "auto"
    settings = json.loads(settings_path.read_text())
    # Old extraction hook pruned; user's own hook preserved.
    assert not settings["hooks"].get("SessionEnd")
    cmds = [
        h["command"] for g in settings["hooks"]["UserPromptSubmit"] for h in g["hooks"]
    ]
    assert cmds == ["bash mine.sh"]
    # Reminder NOT installed (plugin owns it).
    assert "SessionStart" not in settings["hooks"]


def test_apply_extract_engine_no_plugin_installs_reminder(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.claude_plugin_installed", lambda **kw: False
    )
    home = tmp_path / "home"
    state = tmp_path / ".brainpalace"
    state.mkdir()

    mode = apply_extract_engine(state, tmp_path, enabled=True, home=home)

    assert mode == "auto"
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    assert "SessionStart" in settings["hooks"]
    script = home / ".claude" / "hooks" / "brainpalace-sessionstart.sh"
    assert script.is_file()
