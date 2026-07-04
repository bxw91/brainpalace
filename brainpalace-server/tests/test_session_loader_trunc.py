"""Phase 2 Task 2 — opt-out of text-turn truncation for the scan corpus."""

from __future__ import annotations

import json
from pathlib import Path

from brainpalace_server.indexing.session_loader import TEXT_TRUNC, load_session


def _write(tmp_path: Path, text: str) -> Path:
    line = json.dumps(
        {
            "type": "user",
            "sessionId": "s1",
            "timestamp": "2026-01-05T10:00:00Z",
            "message": {"role": "user", "content": text},
        }
    )
    p = tmp_path / "s1.jsonl"
    p.write_text(line + "\n", encoding="utf-8")
    return p


def test_default_still_truncates(tmp_path: Path) -> None:
    p = _write(tmp_path, "word " * 1000)  # 5000 chars
    _, turns = load_session(p)
    assert len(turns) == 1
    assert len(turns[0].text) <= TEXT_TRUNC + 2  # +2 for the " …" suffix


def test_zero_disables_truncation(tmp_path: Path) -> None:
    long_text = "word " * 1000
    p = _write(tmp_path, long_text)
    _, turns = load_session(p, text_trunc=0)
    assert turns[0].text == " ".join(long_text.split())  # whitespace-normalised, full
