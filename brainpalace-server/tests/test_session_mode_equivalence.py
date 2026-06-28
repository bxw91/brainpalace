"""``extraction.mode`` is the sole engine selector for both consumers.

Replaces the old Plan 4 H4 guardrail (which tested that session fell back to
``session_extraction.mode``). The new contract: ``resolve_extraction_mode``
reads ``extraction.mode`` for BOTH consumers; ``session_extraction.mode`` is
ignored entirely regardless of what is written there.
"""

import pytest

from brainpalace_server.config.extraction_config import resolve_extraction_mode


@pytest.mark.parametrize(
    "body,expected",
    [
        # extraction block present — governs both consumers
        ("extraction:\n  mode: subagent\n", "subagent"),
        ("extraction:\n  mode: provider\n", "provider"),
        ("extraction:\n  mode: auto\n", "auto"),
        ("extraction:\n  mode: off\n", "off"),
    ],
)
def test_extraction_mode_governs_session(tmp_path, body, expected):
    p = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    assert resolve_extraction_mode("session", p) == expected
    assert resolve_extraction_mode("doc", p) == expected


@pytest.mark.parametrize(
    "body",
    [
        "embedding:\n  provider: openai\n",  # absent block → off
        "session_extraction:\n  mode: subagent\n",  # legacy key ignored
        "session_extraction:\n  mode: provider\n",  # legacy key ignored
        "session_extraction:\n  mode: auto\n",  # legacy key ignored
    ],
)
def test_absent_extraction_block_always_off(tmp_path, body):
    p = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    assert resolve_extraction_mode("session", p) == "off"
    assert resolve_extraction_mode("doc", p) == "off"
