"""Tests for `install-session-hooks` — SessionStart reminder only + prune.

The two extraction hooks (SessionEnd queue, UserPromptSubmit drain) are now
owned by the Claude Code plugin. `install-session-hooks` installs only the
SessionStart reminder and prunes any old extraction hooks a prior version wrote.
"""

from __future__ import annotations

import json
import stat

from brainpalace_cli.commands.session_hooks import (
    REMINDER_EVENT,
    install_session_hooks,
    merge_hook_settings,
    prune_extraction_hooks,
)


def test_installs_only_sessionstart(tmp_path) -> None:
    install_session_hooks(tmp_path)
    s = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert set(s["hooks"]) == {"SessionStart"}
    script = tmp_path / ".claude" / "hooks" / "brainpalace-sessionstart.sh"
    assert script.is_file()
    assert stat.S_IMODE(script.stat().st_mode) & 0o755 == 0o755


def test_reminder_event_constant() -> None:
    assert REMINDER_EVENT == "SessionStart"


def test_prune_removes_old_extraction_hooks(tmp_path) -> None:
    settings = {
        "hooks": {
            "SessionEnd": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "bash ~/.claude/hooks/brainpalace-sessionend.sh",
                        }
                    ]
                }
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                "bash ~/.claude/hooks/"
                                "brainpalace-userpromptsubmit-drain.sh"
                            ),
                        }
                    ]
                },
                {"hooks": [{"type": "command", "command": "bash my-own.sh"}]},
            ],
        }
    }
    pruned = prune_extraction_hooks(settings)
    assert "SessionEnd" not in pruned["hooks"] or pruned["hooks"]["SessionEnd"] == []
    cmds = [
        h["command"] for g in pruned["hooks"]["UserPromptSubmit"] for h in g["hooks"]
    ]
    assert "bash my-own.sh" in cmds
    assert not any("brainpalace-userpromptsubmit-drain.sh" in c for c in cmds)


def test_prune_preserves_sessionstart_reminder() -> None:
    settings = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                "bash ~/.claude/hooks/brainpalace-sessionstart.sh"
                            ),
                        }
                    ]
                }
            ],
            "SessionEnd": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "bash ~/.claude/hooks/brainpalace-sessionend.sh",
                        }
                    ]
                }
            ],
        }
    }
    pruned = prune_extraction_hooks(settings)
    cmds = [h["command"] for g in pruned["hooks"]["SessionStart"] for h in g["hooks"]]
    assert any("brainpalace-sessionstart.sh" in c for c in cmds)


def test_merge_is_idempotent() -> None:
    hooks = {"SessionStart": "bash ~/.claude/hooks/brainpalace-sessionstart.sh"}
    once = merge_hook_settings({}, hooks)
    twice = merge_hook_settings(once, hooks)
    assert len(twice["hooks"]["SessionStart"]) == 1


def test_merge_does_not_mutate_input() -> None:
    original: dict = {}
    merge_hook_settings(
        original, {"SessionStart": "bash ~/.claude/hooks/brainpalace-sessionstart.sh"}
    )
    assert original == {}


def test_install_backs_up_existing_settings(tmp_path) -> None:
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True)
    settings_path = claude / "settings.json"
    settings_path.write_text(json.dumps({"hooks": {"SessionStart": []}}))

    install_session_hooks(tmp_path)

    assert (claude / "settings.json.bak").is_file()
