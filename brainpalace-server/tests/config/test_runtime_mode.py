"""Tests for the read-only runtime-mode resolver."""

from pathlib import Path

import yaml

from brainpalace_server.config.runtime_mode import is_read_only


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_default_is_false(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAINPALACE_READ_ONLY", raising=False)
    assert is_read_only(_write(tmp_path, {})) is False


def test_config_true(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAINPALACE_READ_ONLY", raising=False)
    assert is_read_only(_write(tmp_path, {"server": {"read_only": True}})) is True


def test_env_overrides_config_false(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAINPALACE_READ_ONLY", "true")
    assert is_read_only(_write(tmp_path, {"server": {"read_only": False}})) is True


def test_env_false_overrides_config_true(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAINPALACE_READ_ONLY", "0")
    assert is_read_only(_write(tmp_path, {"server": {"read_only": True}})) is False


def test_bad_config_is_false(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAINPALACE_READ_ONLY", raising=False)
    p = tmp_path / "config.yaml"
    p.write_text(": not valid yaml :")
    assert is_read_only(p) is False
