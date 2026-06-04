"""Claude Code plugin detection (Task 2) — global, project, marketplace cache."""

from __future__ import annotations

import json

from click.testing import CliRunner

from brainpalace_cli.commands.plugin_detect import (
    claude_plugin_installed,
    plugin_group,
)


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


def test_marketplace_cache_alone_is_not_installed(tmp_path) -> None:
    # A plugin cached under a marketplace clone is NOT an installed plugin —
    # adding a marketplace must not read as "installed" (registry is authoritative).
    home = tmp_path / "home"
    (
        home
        / ".claude"
        / "plugins"
        / "cache"
        / "brainpalace-marketplace"
        / "brainpalace"
    ).mkdir(parents=True)
    assert claude_plugin_installed(home=home) is False


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


def test_unparseable_registry_falls_back_to_install_dirs_only(tmp_path) -> None:
    # Registry unreadable → fall back to explicit install dirs ONLY. A marketplace
    # cache clone does NOT count; a real install dir does.
    home = tmp_path / "home"
    p = home / ".claude" / "plugins"
    p.mkdir(parents=True)
    (p / "installed_plugins.json").write_text("{ not json")
    (p / "cache" / "brainpalace-marketplace" / "brainpalace").mkdir(parents=True)
    assert claude_plugin_installed(home=home) is False  # cache clone ≠ installed
    (p / "brainpalace").mkdir()  # explicit install dir
    assert claude_plugin_installed(home=home) is True


def test_plugin_status_json_installed(monkeypatch) -> None:
    monkeypatch.setattr(
        "brainpalace_cli.commands.plugin_detect.claude_plugin_installed",
        lambda: True,
    )
    result = CliRunner().invoke(plugin_group, ["status", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"installed": True}


def test_plugin_status_json_absent(monkeypatch) -> None:
    monkeypatch.setattr(
        "brainpalace_cli.commands.plugin_detect.claude_plugin_installed",
        lambda: False,
    )
    result = CliRunner().invoke(plugin_group, ["status", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"installed": False}
