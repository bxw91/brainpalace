"""Tests for write_default_provider_config (Phase L + Phase L1 follow-up)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from brainpalace_cli.commands.init import (
    DEFAULT_PROVIDER_CONFIG,
    write_default_provider_config,
)


@pytest.fixture
def isolated_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point get_xdg_config_dir() at an empty tmp dir so tests don't see
    the developer's real ~/.config/brainpalace/config.yaml."""
    fake_xdg = tmp_path / "_xdg"
    fake_xdg.mkdir()
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.get_xdg_config_dir", lambda: fake_xdg
    )
    return fake_xdg


def test_writes_default_config_when_absent(tmp_path: Path, isolated_xdg: Path) -> None:
    """No config.yaml, no XDG global → hardcoded default written."""
    written = write_default_provider_config(tmp_path)
    assert written is True

    config_path = tmp_path / "config.yaml"
    assert config_path.exists()

    data = yaml.safe_load(config_path.read_text())
    assert data["graphrag"]["enabled"] is True
    assert data["graphrag"]["use_code_metadata"] is True
    assert data["graphrag"]["store_type"] == "simple"
    # docs not opt-in by default (no LLM cost)
    assert "doc_extractor" not in data["graphrag"]


def test_idempotent_when_present(tmp_path: Path, isolated_xdg: Path) -> None:
    """Existing config.yaml → no overwrite without force."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("existing: true\n")

    written = write_default_provider_config(tmp_path)
    assert written is False
    assert config_path.read_text() == "existing: true\n"


def test_force_overwrites(tmp_path: Path, isolated_xdg: Path) -> None:
    """force=True → existing config.yaml replaced with defaults."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("old: true\n")

    written = write_default_provider_config(tmp_path, force=True)
    assert written is True

    data = yaml.safe_load(config_path.read_text())
    assert "graphrag" in data
    assert "old" not in data


def test_defaults_match_constant(tmp_path: Path, isolated_xdg: Path) -> None:
    """Written config matches DEFAULT_PROVIDER_CONFIG (no silent drift)."""
    write_default_provider_config(tmp_path)
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert data == DEFAULT_PROVIDER_CONFIG


def test_copies_xdg_global_when_present(tmp_path: Path, isolated_xdg: Path) -> None:
    """User has ~/.config/brainpalace/config.yaml → init copies it
    instead of writing the hardcoded default. Respects user provider choice."""
    xdg_config = isolated_xdg / "config.yaml"
    user_config = {
        "embedding": {"provider": "openai", "model": "text-embedding-3-large"},
        "summarization": {"provider": "openai", "model": "gpt-4o-mini"},
        "graphrag": {"enabled": True, "use_code_metadata": True},
    }
    xdg_config.write_text(yaml.safe_dump(user_config))

    written = write_default_provider_config(tmp_path)
    assert written is True

    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    # Came from XDG, NOT the hardcoded Anthropic default.
    assert data["summarization"]["provider"] == "openai"
    assert data["summarization"]["model"] == "gpt-4o-mini"
