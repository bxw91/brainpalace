"""Tests for plugin version detection + the `brainpalace update` plugin tail."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from brainpalace_cli.cli import cli
from brainpalace_cli.commands import plugin_detect, update


def _write_registry(home: Path, key: str, version: str) -> None:
    reg = home / ".claude" / "plugins"
    reg.mkdir(parents=True, exist_ok=True)
    (reg / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {key: [{"version": version}]}}),
        encoding="utf-8",
    )


# --- pure helpers ----------------------------------------------------------


def test_installed_version_and_target_from_registry(tmp_path: Path) -> None:
    _write_registry(tmp_path, "brainpalace@brainpalace-marketplace", "26.5.1")
    assert plugin_detect.installed_plugin_version(tmp_path) == "26.5.1"
    assert (
        plugin_detect.plugin_update_target(tmp_path)
        == "brainpalace@brainpalace-marketplace"
    )


def test_installed_version_none_when_absent(tmp_path: Path) -> None:
    assert plugin_detect.installed_plugin_version(tmp_path) is None
    # Target falls back to the canonical qualified name.
    assert plugin_detect.plugin_update_target(tmp_path) == (
        "brainpalace@brainpalace-marketplace"
    )


@pytest.mark.parametrize(
    "installed,available,expected",
    [
        ("26.5.1", "26.6.5", True),  # newer minor
        ("26.6.5", "26.6.43", True),  # monthly counter, numeric not lexical
        ("26.6.43", "26.6.43", False),  # equal
        ("26.7.0", "26.6.9", False),  # available older
        (None, "26.6.5", False),  # unknown installed → never nag
        ("26.5.1", None, False),  # unknown available → never nag
    ],
)
def test_plugin_update_available(installed, available, expected) -> None:
    assert plugin_detect.plugin_update_available(installed, available) is expected


def test_available_version_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def _boom(*_a, **_k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", _boom)
    assert plugin_detect.available_plugin_version() is None


def test_available_version_reads_latest_release_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two-step: latest-release API → plugin.json at that tag (NOT main).
    import httpx

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    seen: list[str] = []

    def _get(url, *_a, **_k):
        seen.append(url)
        if url == plugin_detect.GITHUB_LATEST_RELEASE_URL:
            return _Resp({"tag_name": "26.6.43"})
        return _Resp({"version": "26.5.1"})  # plugin.json at the tag

    monkeypatch.setattr(httpx, "get", _get)
    assert plugin_detect.available_plugin_version() == "26.5.1"
    # The manifest was fetched at the release tag, not at /main/.
    assert any("/26.6.43/" in u for u in seen)
    assert not any("/main/" in u for u in seen)


# --- plugin status surfacing (Q3) ------------------------------------------


def test_plugin_status_json_reports_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_detect, "claude_plugin_installed", lambda: True)
    monkeypatch.setattr(plugin_detect, "installed_plugin_version", lambda: "26.5.1")
    monkeypatch.setattr(plugin_detect, "available_plugin_version", lambda: "26.6.5")
    res = CliRunner().invoke(cli, ["plugin", "status", "--json"])
    data = json.loads(res.output)
    assert data == {
        "installed": True,
        "version": "26.5.1",
        "latest": "26.6.5",
        "update_available": True,
    }


# --- update tail flow ------------------------------------------------------


def _patch_flow(monkeypatch, *, installed, available, which, returncode=0):
    monkeypatch.setattr(plugin_detect, "claude_plugin_installed", lambda: True)
    monkeypatch.setattr(plugin_detect, "installed_plugin_version", lambda: installed)
    monkeypatch.setattr(plugin_detect, "available_plugin_version", lambda: available)
    monkeypatch.setattr(plugin_detect, "plugin_update_target", lambda: "brainpalace@bm")
    monkeypatch.setattr(update.shutil, "which", lambda _: which)
    calls: list[list[str]] = []

    def _run(cmd, **_k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode)

    monkeypatch.setattr(update.subprocess, "run", _run)
    return calls


def _flow_output(yes: bool = True) -> str:
    from io import StringIO

    from rich.console import Console

    buf = StringIO()
    update.console = Console(file=buf, width=80)
    try:
        update._plugin_update_flow(yes)
    finally:
        update.console = Console()
    return buf.getvalue()


def test_flow_autoruns_with_yes_then_box(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_flow(
        monkeypatch, installed="26.5.1", available="26.6.5", which="/usr/bin/claude"
    )
    out = _flow_output(yes=True)
    assert ["claude", "plugin", "update", "brainpalace@bm"] in calls
    assert "plugin updated to 26.6.5" in out
    assert "ACTION REQUIRED" in out and "Restart Claude Code" in out


def test_flow_failure_shows_manual_command(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_flow(
        monkeypatch,
        installed="26.5.1",
        available="26.6.5",
        which="/usr/bin/claude",
        returncode=1,
    )
    out = _flow_output(yes=True)
    assert "plugin update failed" in out
    assert "claude plugin update brainpalace@bm" in out
    assert "ACTION REQUIRED" in out  # restart box still shown


def test_flow_no_claude_binary_shows_manual_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_flow(monkeypatch, installed="26.5.1", available="26.6.5", which=None)
    out = _flow_output(yes=True)
    assert calls == []  # never tried to run
    assert "claude plugin update brainpalace@bm" in out
    assert "ACTION REQUIRED" in out


def test_flow_up_to_date_no_box(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_flow(
        monkeypatch, installed="26.6.5", available="26.6.5", which="/usr/bin/claude"
    )
    out = _flow_output(yes=True)
    assert calls == []
    assert "up to date" in out
    assert "ACTION REQUIRED" not in out  # no change → no restart nag
