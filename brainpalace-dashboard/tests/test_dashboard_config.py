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


def test_autostart_defaults_true(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cfgmod.load_dashboard_config().autostart is True


def test_autostart_reads_and_roundtrips_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = tmp_path / "brainpalace"  # type: ignore[operator]
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("dashboard:\n  autostart: false\n")
    assert cfgmod.load_dashboard_config().autostart is False

    # Saving autostart back True persists and reloads.
    cfgmod.save_dashboard_config({"autostart": True})
    assert cfgmod.load_dashboard_config().autostart is True


def test_display_format_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = cfgmod.load_dashboard_config()
    assert cfg.time_format == "24h"
    assert cfg.date_format == "dd.mm.yyyy"


def test_display_format_reads_and_roundtrips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfgmod.save_dashboard_config({"time_format": "12h", "date_format": "yyyy-mm-dd"})
    cfg = cfgmod.load_dashboard_config()
    assert cfg.time_format == "12h"
    assert cfg.date_format == "yyyy-mm-dd"


def test_display_format_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with pytest.raises(cfgmod.DashboardConfigError):
        cfgmod.save_dashboard_config({"time_format": "36h"})
    with pytest.raises(cfgmod.DashboardConfigError):
        cfgmod.save_dashboard_config({"date_format": "ddmmyy"})


def test_display_format_invalid_yaml_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = tmp_path / "brainpalace"  # type: ignore[operator]
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("dashboard:\n  time_format: bogus\n")
    # A garbage on-disk value must not crash the loader; defaults win.
    assert cfgmod.load_dashboard_config().time_format == "24h"
