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
    (d / "dashboard.yaml").write_text("port: 9000\ntoken: s3cret\n")
    cfg = cfgmod.load_dashboard_config()
    assert cfg.port == 9000
    assert cfg.token == "s3cret"
    # Unspecified fields keep their defaults.
    assert cfg.host == "127.0.0.1"
    assert cfg.poll_s == 5


def test_first_load_migrates_legacy_block(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = tmp_path / "brainpalace"
    d.mkdir(parents=True)
    # Legacy install: dashboard config lives in the config.yaml block, alongside
    # an unrelated section that MUST survive.
    (d / "config.yaml").write_text(
        "embedding:\n  provider: openai\ndashboard:\n  port: 9000\n"
    )

    cfg = cfgmod.load_dashboard_config()
    assert cfg.port == 9000

    import yaml

    # Block moved into dashboard.yaml...
    dash = yaml.safe_load((d / "dashboard.yaml").read_text())
    assert dash == {"port": 9000}
    # ...and stripped from config.yaml, leaving the unrelated section intact.
    cfgyaml = yaml.safe_load((d / "config.yaml").read_text())
    assert "dashboard" not in cfgyaml
    assert cfgyaml["embedding"] == {"provider": "openai"}


def test_no_migration_when_dashboard_yaml_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = tmp_path / "brainpalace"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("dashboard:\n  port: 9000\n")
    (d / "dashboard.yaml").write_text("port: 7777\n")

    cfg = cfgmod.load_dashboard_config()
    # dashboard.yaml wins; the legacy block is NOT migrated over it.
    assert cfg.port == 7777
    import yaml

    assert yaml.safe_load((d / "config.yaml").read_text())["dashboard"] == {
        "port": 9000
    }


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


def test_save_is_sparse_drops_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfgmod.save_dashboard_config({"port": 9000, "poll_s": 5})  # poll_s == default
    import yaml

    on_disk = yaml.safe_load((tmp_path / "brainpalace" / "dashboard.yaml").read_text())
    assert on_disk == {"port": 9000}  # default poll_s not persisted


def test_effective_reports_file_vs_default(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfgmod.save_dashboard_config({"port": 9000})
    eff = cfgmod.dashboard_config_effective()
    assert eff["port"] == {"value": 9000, "source": "file"}
    assert eff["host"] == {"value": "127.0.0.1", "source": "default"}
    assert eff["token"]["source"] == "default"
    assert eff["token"]["value"] == ""  # unset token reads as empty, never a real value


def test_effective_masks_set_token(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfgmod.save_dashboard_config({"token": "s3cret"})
    eff = cfgmod.dashboard_config_effective()
    assert eff["token"] == {"value": cfgmod.TOKEN_MASK, "source": "file"}


def test_unset_removes_field_and_reports_default(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfgmod.save_dashboard_config({"port": 9000})
    res = cfgmod.unset_dashboard_config(["port"])
    assert res["removed"] == ["port"]
    assert res["effective"]["port"] == {"value": 8787, "source": "default"}
    import yaml

    on_disk = (
        yaml.safe_load((tmp_path / "brainpalace" / "dashboard.yaml").read_text()) or {}
    )
    assert "port" not in on_disk
