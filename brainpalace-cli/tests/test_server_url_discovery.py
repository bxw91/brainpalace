"""Tests for get_server_url() CWD-based discovery wiring (B2-B4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_cli import config as cfg


def test_env_var_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """BRAINPALACE_URL takes precedence; discovery is not consulted."""
    monkeypatch.setenv("BRAINPALACE_URL", "http://env:9000")
    calls: list[int] = []

    def _disco(start: Path | None = None) -> str | None:
        calls.append(1)
        return "http://discovered:1"

    monkeypatch.setattr("brainpalace_cli.config.discover_server_url", _disco)
    assert cfg.get_server_url() == "http://env:9000"
    assert calls == []


def test_discovery_used_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no env var, a discovered live server URL is returned."""
    monkeypatch.delenv("BRAINPALACE_URL", raising=False)

    def _disco(start: Path | None = None) -> str | None:
        return "http://discovered:8123"

    monkeypatch.setattr("brainpalace_cli.config.discover_server_url", _disco)
    assert cfg.get_server_url() == "http://discovered:8123"


def test_falls_back_to_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env var, no discovered server, AND no owning project → config.server.url."""
    monkeypatch.delenv("BRAINPALACE_URL", raising=False)

    def _disco(start: Path | None = None) -> str | None:
        return None

    monkeypatch.setattr("brainpalace_cli.config.discover_server_url", _disco)
    # No initialized project owns the CWD → the config fallback is legitimate.
    monkeypatch.setattr(
        "brainpalace_cli.config.discover_project_dir", lambda start=None: None
    )
    conf = cfg.BrainPalaceConfig()
    conf.server.url = "http://from-config:7000"
    assert cfg.get_server_url(conf) == "http://from-config:7000"


def test_raises_when_project_owns_cwd_but_no_live_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An owning project with no validated server must NOT fall back to another
    server (the wrong-server bug). get_server_url raises instead."""
    monkeypatch.delenv("BRAINPALACE_URL", raising=False)
    monkeypatch.setattr(
        "brainpalace_cli.config.discover_server_url", lambda start=None: None
    )
    monkeypatch.setattr(
        "brainpalace_cli.config.discover_project_dir", lambda start=None: tmp_path
    )
    conf = cfg.BrainPalaceConfig()
    conf.server.url = "http://some-other-project:8000"
    with pytest.raises(cfg.ServerNotReachableError) as exc:
        cfg.get_server_url(conf)
    assert exc.value.project == tmp_path
