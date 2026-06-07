"""Tests for the ``brainpalace dashboard`` CLI command group."""

from __future__ import annotations

import sys
import types

import pytest
from click.testing import CliRunner

from brainpalace_cli.cli import cli


def _install_fake_dashboard(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Provide a stub ``brainpalace_dashboard.server`` module for the command.

    Mirrors what the real package exposes; the command lazily imports it.
    """
    pkg = types.ModuleType("brainpalace_dashboard")
    srv = types.ModuleType("brainpalace_dashboard.server")
    pkg.server = srv  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "brainpalace_dashboard", pkg)
    monkeypatch.setitem(sys.modules, "brainpalace_dashboard.server", srv)
    return srv


def test_dashboard_start_invokes_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _install_fake_dashboard(monkeypatch)
    srv.launch_dashboard = lambda **k: "http://127.0.0.1:8787/dashboard/"  # type: ignore[attr-defined]
    res = CliRunner().invoke(cli, ["dashboard", "start", "--no-open"])
    assert res.exit_code == 0, res.output
    assert "8787" in res.output


def test_dashboard_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _install_fake_dashboard(monkeypatch)
    srv.stop_dashboard = lambda: {"status": "stopped", "pid": 1}  # type: ignore[attr-defined]
    res = CliRunner().invoke(cli, ["dashboard", "stop"])
    assert res.exit_code == 0, res.output
    assert "stopped" in res.output.lower()


def test_dashboard_status_running(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _install_fake_dashboard(monkeypatch)
    srv.dashboard_status = lambda: {  # type: ignore[attr-defined]
        "status": "running",
        "pid": 42,
        "port": 8787,
        "base_url": "http://127.0.0.1:8787/dashboard/",
        "healthy": True,
    }
    res = CliRunner().invoke(cli, ["dashboard", "status"])
    assert res.exit_code == 0, res.output
    assert "running" in res.output.lower()
    assert "8787" in res.output


def test_dashboard_status_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _install_fake_dashboard(monkeypatch)
    srv.dashboard_status = lambda: {"status": "not_running"}  # type: ignore[attr-defined]
    res = CliRunner().invoke(cli, ["dashboard", "status"])
    assert res.exit_code == 0, res.output
    assert "not running" in res.output.lower() or "not_running" in res.output.lower()


def test_dashboard_missing_package_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the dashboard package isn't installed, print a friendly hint."""
    # Ensure import fails.
    monkeypatch.setitem(sys.modules, "brainpalace_dashboard", None)
    res = CliRunner().invoke(cli, ["dashboard", "start", "--no-open"])
    assert res.exit_code != 0
    assert "brainpalace-dashboard" in res.output


def test_dashboard_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _install_fake_dashboard(monkeypatch)
    srv.dashboard_status = lambda: {"status": "not_running"}  # type: ignore[attr-defined]
    res = CliRunner().invoke(cli, ["dashboard", "status", "--json"])
    assert res.exit_code == 0, res.output
    import json

    parsed = json.loads(res.output)
    assert parsed["status"] == "not_running"
