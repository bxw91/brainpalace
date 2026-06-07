"""Tests for the dashboard config loader (``dashboard:`` section of XDG config)."""

from __future__ import annotations

import pytest

import brainpalace_dashboard.config as cfgmod


def test_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = cfgmod.load_dashboard_config()
    assert cfg.port == 8787
    assert cfg.host == "127.0.0.1"
    assert cfg.poll_s == 5
    assert cfg.token is None


def test_reads_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = tmp_path / "brainpalace"  # type: ignore[operator]
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("dashboard:\n  port: 9000\n  token: s3cret\n")
    cfg = cfgmod.load_dashboard_config()
    assert cfg.port == 9000
    assert cfg.token == "s3cret"
    # Unspecified fields keep their defaults.
    assert cfg.host == "127.0.0.1"
    assert cfg.poll_s == 5


def test_missing_config_file_uses_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = cfgmod.load_dashboard_config()
    assert cfg.port == 8787
