"""The `brainpalace status` pink dashboard box (always shown)."""

from __future__ import annotations

import pytest
from rich.console import Console

from brainpalace_cli.commands import _dashboard_url


def _render(monkeypatch: pytest.MonkeyPatch, info: dict) -> str:
    monkeypatch.setattr(_dashboard_url, "dashboard_status_info", lambda: info)
    console = Console(record=True, width=100)
    _dashboard_url.render_dashboard_status(console=console)
    return console.export_text()


def test_box_shows_url_when_running(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _render(
        monkeypatch,
        {
            "status": "running",
            "base_url": "http://127.0.0.1:8787",
            "healthy": True,
            "port": 8787,
        },
    )
    assert "Web Dashboard" in out
    assert "http://127.0.0.1:8787" in out
    assert "running" in out
    assert "healthy" in out


def test_box_shows_notice_when_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _render(monkeypatch, {"status": "stopped"})
    assert "Web Dashboard" in out
    assert "not running" in out
    assert "brainpalace dashboard start" in out


def test_box_shows_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _render(
        monkeypatch,
        {"status": "running", "base_url": "http://x:8787", "healthy": False},
    )
    assert "unhealthy" in out


def test_box_shows_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    # CLI-only env (no dashboard package, e.g. Python < 3.12).
    out = _render(monkeypatch, {"status": "not_installed"})
    assert "Web Dashboard" in out
    assert "not installed" in out
