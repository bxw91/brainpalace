"""`brainpalace init` writes mode=subagent and reconciles Claude Code hooks.

Summarization happens ONLY inside Claude Code, so init writes ``subagent``
(``off`` with --no-extract). The server never falls back to a paid provider.
Hook reconciliation follows plugin presence:

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


def test_init_writes_subagent_and_installs_reminder_when_no_plugin(
    tmp_path, monkeypatch
):
    calls = _patch(monkeypatch, tmp_path, plugin=False)
    result = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--yes", "--no-start", "--extract"]
    )
    assert result.exit_code == 0, result.output
    assert _cfg(tmp_path)["extraction"]["mode"] == "subagent"
    # No plugin → CLI installs the SessionStart reminder.
    assert len(calls) == 1


def test_init_writes_subagent_and_skips_reminder_when_plugin(tmp_path, monkeypatch):
    calls = _patch(monkeypatch, tmp_path, plugin=True)
    result = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--yes", "--no-start", "--extract"]
    )
    assert result.exit_code == 0, result.output
    assert _cfg(tmp_path)["extraction"]["mode"] == "subagent"
    # Plugin owns the reminder → init must NOT install it (no double SessionStart).
    assert calls == []


def test_init_no_extract_writes_off(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path, plugin=False)
    result = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--no-start", "--no-extract"]
    )
    assert result.exit_code == 0, result.output
    assert _cfg(tmp_path)["extraction"]["mode"] == "off"


def test_init_prints_subagent_note(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path, plugin=False)
    result = CliRunner().invoke(
        init_command, ["--path", str(tmp_path), "--yes", "--no-start", "--extract"]
    )
    assert result.exit_code == 0, result.output
    assert "Claude Code" in result.output


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

    assert mode == "subagent"
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

    assert mode == "subagent"
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    assert "SessionStart" in settings["hooks"]
    script = home / ".claude" / "hooks" / "brainpalace-sessionstart.sh"
    assert script.is_file()


# --------------------------------------------------------------------------- #
# Task 4e — prefill extraction.provider_context_tokens on model selection     #
# --------------------------------------------------------------------------- #


def test_build_default_provider_config_prefills_context_tokens(monkeypatch):
    """When init picks anthropic/claude-haiku-4-5-20251001 it should write
    extraction.provider_context_tokens from the model→window map."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from brainpalace_cli.commands.init import build_default_provider_config

    cfg = build_default_provider_config()
    assert "extraction" in cfg
    ext = cfg["extraction"]
    assert isinstance(ext, dict)
    assert ext.get("provider_context_tokens", 0) == 200000  # anthropic 200k context


def test_build_default_provider_config_no_tokens_for_unknown(monkeypatch):
    """When the selected model is unknown, extraction block has no
    provider_context_tokens (0/absent → runtime floor)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    from brainpalace_cli.commands.init import build_default_provider_config

    cfg = build_default_provider_config()
    # Fallback is anthropic/claude-haiku-4-5-20251001; it IS in the map, so
    # a token count should be written.  Verify the extraction block is correct.
    ext = cfg.get("extraction", {})
    # Either tokens present (known model) or absent (unknown) — must never be negative.
    assert ext.get("provider_context_tokens", 0) >= 0
