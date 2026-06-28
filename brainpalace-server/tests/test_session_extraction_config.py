"""``session_extraction:`` config block — quiescence gate only.

``mode`` has been removed from ``SessionExtractionConfig``; the engine selector
now lives exclusively in ``extraction.mode`` (``ExtractionConfig``). These tests
cover what ``SessionExtractionConfig`` still owns: ``quiescence_seconds``.
"""

from __future__ import annotations

from pathlib import Path

from brainpalace_server.config.session_config import (
    SessionExtractionConfig,
    load_session_extraction_config,
)


def _write(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(body)
    return cfg


def test_default_quiescence_is_1800() -> None:
    assert SessionExtractionConfig().quiescence_seconds == 1800


def test_no_mode_field_on_model() -> None:
    # Confirm the removed field is truly gone from the model.
    assert "mode" not in SessionExtractionConfig.model_fields


def test_absent_block_defaults_quiescence(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "session_indexing:\n  enabled: true\n")
    assert load_session_extraction_config(cfg).quiescence_seconds == 1800


def test_parses_quiescence_seconds(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "session_extraction:\n  quiescence_seconds: 600\n")
    assert load_session_extraction_config(cfg).quiescence_seconds == 600


def test_stray_mode_key_is_silently_discarded(tmp_path: Path) -> None:
    # A legacy ``mode: subagent`` in the yaml must not raise — the field filter
    # discards unknown keys. quiescence_seconds still parses correctly.
    cfg = _write(
        tmp_path, "session_extraction:\n  mode: subagent\n  quiescence_seconds: 900\n"
    )
    result = load_session_extraction_config(cfg)
    assert result.quiescence_seconds == 900


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    result = load_session_extraction_config(tmp_path / "nope.yaml")
    assert result.quiescence_seconds == 1800
