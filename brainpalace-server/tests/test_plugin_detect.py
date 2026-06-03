"""Server-side Claude Code plugin detection — mirror of the CLI contract.

Registry-first parse of ~/.claude/plugins/installed_plugins.json, dir-glob
fallback. Keep in sync with brainpalace-cli's plugin_detect.
"""

from __future__ import annotations

import json

from brainpalace_server.services.plugin_detect import claude_plugin_installed


def _registry(home, keys) -> None:
    p = home / ".claude" / "plugins"
    p.mkdir(parents=True, exist_ok=True)
    (p / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {k: [{"scope": "user"}] for k in keys}})
    )


def test_detects_via_installed_registry(tmp_path) -> None:
    home = tmp_path / "home"
    _registry(home, ["brainpalace@brainpalace-marketplace", "caveman@caveman"])
    assert claude_plugin_installed(home=home) is True


def test_registry_without_brainpalace_is_false(tmp_path) -> None:
    home = tmp_path / "home"
    _registry(home, ["caveman@caveman"])
    assert claude_plugin_installed(home=home) is False


def test_unparseable_registry_falls_back_to_dirs(tmp_path) -> None:
    home = tmp_path / "home"
    p = home / ".claude" / "plugins"
    p.mkdir(parents=True)
    (p / "installed_plugins.json").write_text("{ not json")
    (p / "cache" / "brainpalace-marketplace" / "brainpalace").mkdir(parents=True)
    assert claude_plugin_installed(home=home) is True


def test_returns_false_when_absent(tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project.mkdir()
    assert claude_plugin_installed(home=home, project=project) is False
