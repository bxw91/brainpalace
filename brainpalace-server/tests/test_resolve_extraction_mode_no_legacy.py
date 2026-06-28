from pathlib import Path

from brainpalace_server.config.extraction_config import resolve_extraction_mode


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return p


def test_absent_extraction_mode_is_off_for_session(tmp_path):
    # No extraction block, and NO legacy session_extraction fallback anymore.
    cfg = _write(tmp_path, "embedding:\n  provider: openai\n")
    assert resolve_extraction_mode("session", cfg) == "off"
    assert resolve_extraction_mode("doc", cfg) == "off"


def test_legacy_session_extraction_mode_is_ignored(tmp_path):
    # A stray legacy key must NOT influence the resolved session mode.
    cfg = _write(tmp_path, "session_extraction:\n  mode: provider\n")
    assert resolve_extraction_mode("session", cfg) == "off"


def test_extraction_mode_governs_both(tmp_path):
    cfg = _write(tmp_path, "extraction:\n  mode: subagent\n")
    assert resolve_extraction_mode("session", cfg) == "subagent"
    assert resolve_extraction_mode("doc", cfg) == "subagent"
