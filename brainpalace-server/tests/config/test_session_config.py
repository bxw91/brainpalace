"""Phase 050 — session_indexing config loading + master kill-switch."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.config.session_config import (
    SessionIndexingConfig,
    load_session_indexing_config,
    resolve_session_capabilities,
    retain_cutoff,
    session_distill_enabled,
)


def test_distill_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # The billable provider distiller is OFF unless explicitly enabled — absent
    # env ⇒ False (mode-independent lock against surprise summarization cost).
    monkeypatch.delenv("SESSION_DISTILL_ENABLED", raising=False)
    assert session_distill_enabled() is False


def test_distill_enabled_only_when_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    for truthy in ("1", "true", "yes", "on", "TRUE", "On"):
        monkeypatch.setenv("SESSION_DISTILL_ENABLED", truthy)
        assert session_distill_enabled() is True
    for falsy in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("SESSION_DISTILL_ENABLED", falsy)
        assert session_distill_enabled() is False


def test_present_block_field_defaults() -> None:
    # Field defaults model a PRESENT block: both capabilities ON, forever.
    cfg = SessionIndexingConfig()
    assert cfg.enabled is True
    assert cfg.archive.enabled is True
    assert cfg.include_user_turns is False
    assert cfg.retain_days == 0
    assert cfg.archive.retain_days == 0
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


# --- capability resolution: archive + index are independent ---


def _caps(cfg_text: str | None, tmp_path: Path):
    if cfg_text is None:
        cfg = load_session_indexing_config(tmp_path / "missing.yaml")
    else:
        f = tmp_path / "config.yaml"
        f.write_text(cfg_text)
        cfg = load_session_indexing_config(f)
    return resolve_session_capabilities(cfg)


def test_absent_block_archive_on_index_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SESSION_INDEXING_ENABLED", raising=False)
    monkeypatch.delenv("SESSION_ARCHIVE_ENABLED", raising=False)
    caps = _caps("embedding:\n  provider: openai\n", tmp_path)
    assert caps.archive_enabled is True
    assert caps.index_enabled is False
    assert caps.tool == "claude-code"


def test_present_block_both_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SESSION_INDEXING_ENABLED", raising=False)
    monkeypatch.delenv("SESSION_ARCHIVE_ENABLED", raising=False)
    caps = _caps("session_indexing:\n  enabled: true\n", tmp_path)
    assert caps.archive_enabled is True
    assert caps.index_enabled is True


def test_archive_disabled_in_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SESSION_ARCHIVE_ENABLED", raising=False)
    caps = _caps(
        "session_indexing:\n  enabled: true\n  archive:\n    enabled: false\n",
        tmp_path,
    )
    assert caps.archive_enabled is False
    assert caps.index_enabled is True


def test_env_switches_force_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SESSION_INDEXING_ENABLED", "false")
    monkeypatch.setenv("SESSION_ARCHIVE_ENABLED", "false")
    caps = _caps("session_indexing:\n  enabled: true\n", tmp_path)
    assert caps.archive_enabled is False
    assert caps.index_enabled is False


def test_archive_retain_days_parses(tmp_path: Path) -> None:
    f = tmp_path / "config.yaml"
    f.write_text(
        "session_indexing:\n  enabled: true\n  archive:\n    retain_days: 14\n"
    )
    cfg = load_session_indexing_config(f)
    assert cfg.archive.retain_days == 14


def test_retain_cutoff_forever_when_le_zero() -> None:
    assert retain_cutoff(0) is None
    assert retain_cutoff(-5) is None


def test_retain_cutoff_positive() -> None:
    now = 1_000_000.0
    assert retain_cutoff(2, now=now) == now - 2 * 86400


def test_quiescence_default_is_1800():
    from brainpalace_server.config.session_config import SessionExtractionConfig

    assert SessionExtractionConfig().quiescence_seconds == 1800


def test_quiescence_parsed_from_block(tmp_path):
    from brainpalace_server.config.session_config import load_session_extraction_config

    cfg = tmp_path / "config.yaml"
    cfg.write_text("session_extraction:\n  mode: subagent\n  quiescence_seconds: 600\n")
    assert load_session_extraction_config(cfg).quiescence_seconds == 600


def test_reconcile_default_is_600():
    from brainpalace_server.config.session_config import SessionArchiveConfig

    assert SessionArchiveConfig().reconcile_seconds == 600
