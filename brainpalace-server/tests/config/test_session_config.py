"""Phase 050 — session_indexing config loading + master kill-switch."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.config.session_config import (
    SessionIndexingConfig,
    load_session_indexing_config,
)


def test_defaults_are_disabled_and_private() -> None:
    cfg = SessionIndexingConfig()
    assert cfg.enabled is False
    assert cfg.include_user_turns is False
    assert cfg.retain_days == 90
    assert cfg.window == 4 and cfg.stride == 2
    assert cfg.watch_debounce_ms == 30000


def test_watch_debounce_override_parses(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "session_indexing:\n  enabled: true\n  watch_debounce_ms: 5000\n"
    )
    cfg = load_session_indexing_config(cfg_file)
    assert cfg.watch_debounce_ms == 5000


def test_absent_block_yields_disabled(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("embedding:\n  provider: openai\n")
    cfg = load_session_indexing_config(cfg_file)
    assert cfg.enabled is False


def test_reads_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SESSION_INDEXING_ENABLED", raising=False)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "session_indexing:\n"
        "  enabled: true\n"
        "  include_user_turns: true\n"
        "  retain_days: 30\n"
        "  window: 5\n"
    )
    cfg = load_session_indexing_config(cfg_file)
    assert cfg.enabled is True
    assert cfg.include_user_turns is True
    assert cfg.retain_days == 30
    assert cfg.window == 5


def test_env_master_switch_forces_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SESSION_INDEXING_ENABLED", "false")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("session_indexing:\n  enabled: true\n")
    cfg = load_session_indexing_config(cfg_file)
    assert cfg.enabled is False


def test_unknown_keys_ignored(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("session_indexing:\n  enabled: true\n  bogus_key: 1\n")
    cfg = load_session_indexing_config(cfg_file)
    assert cfg.enabled is True


def test_archive_defaults_on_when_sessions_enabled() -> None:
    cfg = SessionIndexingConfig(enabled=True)
    assert cfg.archive.enabled is True
    assert cfg.archive.dir == ".brainpalace/session_archive"


def test_archive_block_overrides_parse() -> None:
    cfg = SessionIndexingConfig(
        enabled=True, archive={"enabled": False, "dir": "/custom/arch"}
    )
    assert cfg.archive.enabled is False
    assert cfg.archive.dir == "/custom/arch"
