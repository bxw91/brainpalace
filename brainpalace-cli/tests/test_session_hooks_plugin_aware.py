"""Plugin-aware behavior of `install_session_hooks` — avoid a double SessionStart.

When the Claude Code plugin is installed it provides SessionStart (+ extraction)
via plugin.json, so the CLI must NOT also install a SessionStart shim, and must
remove any CLI shim a prior version left (self-heal).
"""

from __future__ import annotations

import json
from pathlib import Path

from brainpalace_cli.commands.plugin_detect import (
    PLUGIN_INSTALL_HINT,
    maybe_plugin_hint,
)
from brainpalace_cli.commands.session_hooks import (
    install_session_hooks,
    prune_cli_session_hooks,
)


def _mark_plugin_installed(home: Path) -> None:
    # Registry-less fallback: an explicit install dir reads as installed.
    (home / ".claude" / "plugins" / "brainpalace").mkdir(parents=True)


def _cli_sessionstart_settings() -> dict:
    return {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                "bash /h/.claude/hooks/brainpalace-sessionstart.sh"
                            ),
                            "timeout": 3,
                        }
                    ]
                }
            ]
        }
    }


def test_skips_install_when_plugin_present(tmp_path: Path) -> None:
    _mark_plugin_installed(tmp_path)
    merged = install_session_hooks(tmp_path)
    # No SessionStart shim written, and no script file created.
    assert merged.get("hooks", {}).get("SessionStart", []) == []
    assert not (tmp_path / ".claude" / "hooks" / "brainpalace-sessionstart.sh").exists()


def test_self_heals_existing_cli_shim_when_plugin_present(tmp_path: Path) -> None:
    _mark_plugin_installed(tmp_path)
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(_cli_sessionstart_settings()))

    merged = install_session_hooks(tmp_path)
    assert merged["hooks"]["SessionStart"] == []  # duplicate removed


def test_installs_when_plugin_absent(tmp_path: Path) -> None:
    merged = install_session_hooks(tmp_path)
    assert set(merged["hooks"]) == {"SessionStart"}
    assert (tmp_path / ".claude" / "hooks" / "brainpalace-sessionstart.sh").is_file()


def test_prune_cli_session_hooks_preserves_other_hooks() -> None:
    settings = _cli_sessionstart_settings()
    settings["hooks"]["SessionStart"][0]["hooks"].append(
        {"type": "command", "command": "bash /h/.claude/hooks/other.sh"}
    )
    pruned = prune_cli_session_hooks(settings)
    cmds = [h["command"] for g in pruned["hooks"]["SessionStart"] for h in g["hooks"]]
    assert cmds == ["bash /h/.claude/hooks/other.sh"]


# --- hint -----------------------------------------------------------------


def test_hint_shown_when_cc_present_plugin_absent(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    assert maybe_plugin_hint(tmp_path) == PLUGIN_INSTALL_HINT


def test_hint_empty_when_plugin_installed(tmp_path: Path) -> None:
    _mark_plugin_installed(tmp_path)
    assert maybe_plugin_hint(tmp_path) == ""


def test_hint_empty_when_no_claude_code(tmp_path: Path) -> None:
    assert maybe_plugin_hint(tmp_path) == ""
