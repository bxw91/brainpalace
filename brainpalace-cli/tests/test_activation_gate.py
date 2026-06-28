"""Activation gate: a plugin-configured project (``init --defer-activation``) is
configured but NOT running until the user starts it once.

Covers the four moving parts of the gate:
  * ``cli.await_first_start`` marker read/write helpers (sparse round-trip);
  * the shared ``passive_autostart_allowed`` chokepoint;
  * the SessionStart hook (passive vector 3) — gated + State-C reminder;
  * the MCP ``--ensure-server`` lifecycle (passive vector 4) — gated;
  * ``brainpalace start`` (manual vector 1) — clears the marker, unless the
    passive ``--no-activate`` signal is set.
"""

from __future__ import annotations

import json

import pytest
import yaml
from click.testing import CliRunner

from brainpalace_cli import config_schema
from brainpalace_cli.commands import hook
from brainpalace_cli.commands import start as start_mod
from brainpalace_cli.commands.start import start_command
from brainpalace_cli.mcp_server import lifecycle


# --------------------------------------------------------------------------- #
# Marker helpers
# --------------------------------------------------------------------------- #
def test_write_marker_then_read_true(tmp_path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    config_schema.write_await_first_start(state, True)
    assert config_schema.read_await_first_start(state) is True
    data = yaml.safe_load((state / "config.yaml").read_text())
    assert data["cli"]["await_first_start"] is True


def test_clear_marker_removes_key_and_empty_cli_block(tmp_path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    config_schema.write_await_first_start(state, True)
    config_schema.write_await_first_start(state, False)
    assert config_schema.read_await_first_start(state) is False
    # Sparse: the now-empty cli block is dropped entirely, not left as {}.
    data = yaml.safe_load((state / "config.yaml").read_text()) or {}
    assert "cli" not in data


def test_clear_marker_preserves_other_cli_keys(tmp_path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(
        yaml.dump({"cli": {"session_autostart": False, "await_first_start": True}})
    )
    config_schema.write_await_first_start(state, False)
    data = yaml.safe_load((state / "config.yaml").read_text())
    assert data["cli"] == {"session_autostart": False}


def test_read_marker_absent_is_false(tmp_path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    assert config_schema.read_await_first_start(state) is False


# --------------------------------------------------------------------------- #
# Shared chokepoint
# --------------------------------------------------------------------------- #
@pytest.fixture
def _no_global_cfg(monkeypatch, tmp_path):
    """Point XDG config at an empty dir so only the project layer matters."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgcfg"))
    monkeypatch.delenv("BRAINPALACE_SESSION_AUTOSTART", raising=False)


def test_passive_allowed_when_no_marker(tmp_path, _no_global_cfg):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    assert config_schema.passive_autostart_allowed(state) is True


def test_passive_blocked_when_marker_set(tmp_path, _no_global_cfg):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    config_schema.write_await_first_start(state, True)
    assert config_schema.passive_autostart_allowed(state) is False


def test_passive_blocked_when_session_autostart_off(tmp_path, _no_global_cfg):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(yaml.dump({"cli": {"session_autostart": False}}))
    assert config_schema.passive_autostart_allowed(state) is False


def test_resolve_session_autostart_env_override(tmp_path, monkeypatch):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(yaml.dump({"cli": {"session_autostart": True}}))
    monkeypatch.setenv("BRAINPALACE_SESSION_AUTOSTART", "off")
    assert config_schema.resolve_session_autostart(state) is False


# --------------------------------------------------------------------------- #
# SessionStart hook (passive vector 3)
# --------------------------------------------------------------------------- #
@pytest.fixture
def _indexed_project(tmp_path, monkeypatch):
    """An indexed project (``.brainpalace/`` present), server down, nudge on."""
    state = tmp_path / ".brainpalace"
    state.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgcfg"))
    monkeypatch.delenv("BRAINPALACE_SESSION_AUTOSTART", raising=False)
    monkeypatch.delenv("BRAINPALACE_SETUP_NUDGE", raising=False)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _x: tmp_path)
    monkeypatch.setattr(hook, "discover_server_url", lambda _x: None)
    monkeypatch.setattr(hook, "nudge", lambda: "NUDGE-GUIDANCE")
    return tmp_path


def test_hook_autostarts_when_no_marker(_indexed_project, monkeypatch, capsys):
    spawned: list = []
    monkeypatch.setattr(hook, "_spawn_autostart", lambda p: spawned.append(p))
    hook._emit_sessionstart()
    assert spawned == [_indexed_project]
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "configured for this project but NOT running" not in ctx


def test_hook_does_not_autostart_when_marker_set(_indexed_project, monkeypatch, capsys):
    config_schema.write_await_first_start(_indexed_project / ".brainpalace", True)
    spawned: list = []
    monkeypatch.setattr(hook, "_spawn_autostart", lambda p: spawned.append(p))
    hook._emit_sessionstart()
    assert spawned == []  # gated: passive vector must NOT start a deferred project
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "configured for this project but NOT running" in ctx  # State C reminder


def test_hook_state_c_silenced_by_optout(_indexed_project, monkeypatch, capsys):
    config_schema.write_await_first_start(_indexed_project / ".brainpalace", True)
    monkeypatch.setenv("BRAINPALACE_SETUP_NUDGE", "off")
    monkeypatch.setattr(hook, "_spawn_autostart", lambda p: None)
    hook._emit_sessionstart()
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "NOT running" not in ctx


# --------------------------------------------------------------------------- #
# MCP --ensure-server (passive vector 4)
# --------------------------------------------------------------------------- #
def test_mcp_ensure_server_gated_by_marker(tmp_path, monkeypatch):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    config_schema.write_await_first_start(state, True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgcfg"))
    monkeypatch.setattr(lifecycle, "discover_project_dir", lambda _x: tmp_path)
    monkeypatch.setattr(lifecycle, "discover_server_url", lambda _x: None)
    monkeypatch.setattr(lifecycle, "resolve_state_dir_with_fallback", lambda _p: state)
    started: list = []
    monkeypatch.setattr(lifecycle, "_start_for", lambda *a, **k: started.append(a))
    lifecycle.ensure_http_server(start=tmp_path)
    assert started == []  # gated: MCP must not auto-start a deferred project


def test_mcp_ensure_server_starts_when_no_marker(tmp_path, monkeypatch):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgcfg"))
    monkeypatch.delenv("BRAINPALACE_SESSION_AUTOSTART", raising=False)
    monkeypatch.setattr(lifecycle, "discover_project_dir", lambda _x: tmp_path)
    monkeypatch.setattr(lifecycle, "discover_server_url", lambda _x: None)
    monkeypatch.setattr(lifecycle, "resolve_state_dir_with_fallback", lambda _p: state)
    started: list = []
    monkeypatch.setattr(lifecycle, "_start_for", lambda *a, **k: started.append(a))
    lifecycle.ensure_http_server(start=tmp_path)
    assert len(started) == 1  # un-gated project boots normally


# --------------------------------------------------------------------------- #
# Manual start clears the marker (vector 1) — using the reuse branch
# --------------------------------------------------------------------------- #
def _setup_reusable(monkeypatch, tmp_path):
    (tmp_path / ".brainpalace").mkdir()
    monkeypatch.setattr(
        start_mod, "find_reusable_server", lambda _p: "http://127.0.0.1:8000"
    )
    monkeypatch.setattr(start_mod, "_ensure_dashboard", lambda **_k: None)


def test_manual_start_clears_marker(monkeypatch, tmp_path):
    _setup_reusable(monkeypatch, tmp_path)
    state = tmp_path / ".brainpalace"
    config_schema.write_await_first_start(state, True)
    result = CliRunner().invoke(start_command, ["--path", str(tmp_path), "--json"])
    assert result.exit_code == 0
    assert config_schema.read_await_first_start(state) is False  # activated


def test_passive_start_keeps_marker(monkeypatch, tmp_path):
    _setup_reusable(monkeypatch, tmp_path)
    state = tmp_path / ".brainpalace"
    config_schema.write_await_first_start(state, True)
    result = CliRunner().invoke(
        start_command, ["--path", str(tmp_path), "--json", "--no-activate"]
    )
    assert result.exit_code == 0
    assert config_schema.read_await_first_start(state) is True  # NOT activated
