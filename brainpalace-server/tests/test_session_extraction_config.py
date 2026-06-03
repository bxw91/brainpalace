"""``session_extraction:`` config block — engine mode resolution (Task 2)."""

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


def test_default_mode_is_subagent() -> None:
    assert SessionExtractionConfig().mode == "subagent"


def test_absent_block_defaults_to_subagent(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "session_indexing:\n  enabled: true\n")
    assert load_session_extraction_config(cfg).mode == "subagent"


def test_parses_auto(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "session_extraction:\n  mode: auto\n")
    assert load_session_extraction_config(cfg).mode == "auto"


def test_parses_subagent_mode(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "session_extraction:\n  mode: subagent\n")
    assert load_session_extraction_config(cfg).mode == "subagent"


def test_parses_provider_mode(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "session_extraction:\n  mode: provider\n")
    assert load_session_extraction_config(cfg).mode == "provider"


def test_parses_off_mode(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "session_extraction:\n  mode: off\n")
    assert load_session_extraction_config(cfg).mode == "off"


def test_invalid_mode_falls_back_to_subagent(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "session_extraction:\n  mode: bogus\n")
    assert load_session_extraction_config(cfg).mode == "subagent"


def test_missing_file_defaults_to_subagent(tmp_path: Path) -> None:
    assert load_session_extraction_config(tmp_path / "nope.yaml").mode == "subagent"
