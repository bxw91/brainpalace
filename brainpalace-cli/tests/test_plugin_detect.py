"""Claude Code plugin detection (Task 2) — global, project, marketplace cache."""

from __future__ import annotations

import json

from brainpalace_cli.commands.plugin_detect import claude_plugin_installed


def test_detects_global_install(tmp_path) -> None:
    home = tmp_path / "home"
    (home / ".claude" / "plugins" / "brainpalace").mkdir(parents=True)
    assert claude_plugin_installed(home=home) is True


def test_detects_project_install(tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    (project / ".claude" / "plugins" / "brainpalace").mkdir(parents=True)
    assert claude_plugin_installed(home=home, project=project) is True


def test_detects_marketplace_cache(tmp_path) -> None:
    home = tmp_path / "home"
    (home / ".claude" / "plugins" / "cache" / "some-market" / "brainpalace").mkdir(
        parents=True
    )
    assert claude_plugin_installed(home=home) is True


def test_returns_false_when_absent(tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    project.mkdir()
    assert claude_plugin_installed(home=home, project=project) is False


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
