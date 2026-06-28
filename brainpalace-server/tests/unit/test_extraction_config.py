"""Plan 4 — shared ExtractionConfig + resolver + provider-enabled env lock."""

from pathlib import Path

from brainpalace_server.config.extraction_config import (
    ExtractionConfig,
    extraction_provider_enabled,
    load_extraction_config,
    resolve_extraction_mode,
)


def _w(p: Path, t: str) -> Path:
    f = p / "config.yaml"
    f.write_text(t, encoding="utf-8")
    return f


def test_model_defaults():
    c = ExtractionConfig()
    assert (c.mode, c.grace_hours, c.drain_batch_size, c.drain_cooldown_seconds) == (
        "off",
        24,
        8,
        300,
    )


def test_defaults(tmp_path):
    c = load_extraction_config(_w(tmp_path, "embedding:\n  provider: openai\n"))
    assert (c.mode, c.grace_hours, c.drain_batch_size, c.drain_cooldown_seconds) == (
        "off",
        24,
        8,
        300,
    )


def test_fields_parsed(tmp_path):
    c = load_extraction_config(
        _w(
            tmp_path,
            "extraction:\n  mode: provider\n  grace_hours: 6\n"
            "  drain_batch_size: 4\n  drain_cooldown_seconds: 60\n",
        )
    )
    assert (c.mode, c.grace_hours, c.drain_batch_size, c.drain_cooldown_seconds) == (
        "provider",
        6,
        4,
        60,
    )


def test_yaml_off_coerced(tmp_path):
    assert (
        load_extraction_config(_w(tmp_path, "extraction:\n  mode: off\n")).mode == "off"
    )


def test_invalid_mode_off(tmp_path):
    assert (
        load_extraction_config(_w(tmp_path, "extraction:\n  mode: bogus\n")).mode
        == "off"
    )


def test_resolve_block_wins_both(tmp_path):
    c = _w(
        tmp_path, "extraction:\n  mode: auto\nsession_extraction:\n  mode: provider\n"
    )
    assert resolve_extraction_mode("doc", c) == "auto"
    assert resolve_extraction_mode("session", c) == "auto"


def test_resolve_legacy_session_extraction_ignored(tmp_path):
    # session_extraction.mode is no longer a fallback — both consumers return off.
    c = _w(tmp_path, "session_extraction:\n  mode: subagent\n")
    assert resolve_extraction_mode("doc", c) == "off"
    assert resolve_extraction_mode("session", c) == "off"


def test_resolve_absent_extraction_block_off_for_both(tmp_path):
    # Absent extraction block → off for both consumers (cost-safe default).
    c = _w(tmp_path, "embedding:\n  provider: openai\n")
    assert resolve_extraction_mode("session", c) == "off"
    assert resolve_extraction_mode("doc", c) == "off"


def test_provider_lock_env(monkeypatch):
    monkeypatch.delenv("EXTRACTION_PROVIDER_ENABLED", raising=False)
    monkeypatch.delenv("SESSION_DISTILL_ENABLED", raising=False)
    assert extraction_provider_enabled() is False
    monkeypatch.setenv("SESSION_DISTILL_ENABLED", "true")  # back-compat
    assert extraction_provider_enabled() is True
    monkeypatch.setenv("EXTRACTION_PROVIDER_ENABLED", "true")
    assert extraction_provider_enabled() is True


# --------------------------------------------------------------------------- #
# Task 4a — resource-guard knobs                                              #
# --------------------------------------------------------------------------- #


def test_resource_guard_defaults(tmp_path):
    c = load_extraction_config(_w(tmp_path, "embedding:\n  provider: openai\n"))
    assert (c.drain_doc_max_per_turn, c.drain_session_max_per_turn) == (4, 2)
    assert (c.max_provider_items_per_hour, c.provider_session_max_chunks) == (60, 6)
    assert (c.provider_context_tokens, c.distill_chunk_chars, c.max_pending) == (
        0,
        0,
        50000,
    )


def test_resource_guard_parsed(tmp_path):
    body = (
        "extraction:\n  drain_doc_max_per_turn: 2\n  max_provider_items_per_hour: 0\n"
        "  provider_context_tokens: 8192\n  max_pending: 100\n"
    )
    c = load_extraction_config(_w(tmp_path, body))
    assert c.drain_doc_max_per_turn == 2 and c.max_provider_items_per_hour == 0
    assert c.provider_context_tokens == 8192 and c.max_pending == 100
