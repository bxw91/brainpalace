"""Tests for the unified per-prompt drain (`extraction_drain.unified_drain`).

Security-critical: the per-prompt directive must contain **ids only, never chunk
text** (H1 — untrusted indexed text never reaches the main model). These tests
pin that invariant (SECRET-DOC-TEXT absence), the cooldown-on-emit stamp (E3),
and the fail-open contract (H3).
"""

from __future__ import annotations

from brainpalace_cli.commands.extraction_drain import unified_drain


def test_unified_drain_groups_ids_no_text(tmp_path, monkeypatch):
    pending = {
        "items": [
            {"source": "doc", "id": "c1", "text": "SECRET-DOC-TEXT"},
            {"source": "doc", "id": "c2", "text": "x"},
            {"source": "session", "id": "s9", "path": "/a/s9.jsonl"},
        ],
        "doc_pending_total": 2,
    }
    monkeypatch.setattr(
        "brainpalace_cli.commands.extraction_drain._fetch_pending",
        lambda url, timeout: pending,
    )
    out = unified_drain(
        tmp_path,
        url="http://x",
        doc_cap=4,
        session_budget=10**9,
        session_cap=2,
        cooldown=300,
        now=1000.0,
    )
    d = out["directive"]
    assert "c1" in d and "c2" in d and "s9" in d
    assert "graph-triplet-extractor" in d and "chat-session-extractor" in d
    assert "SECRET-DOC-TEXT" not in d  # H1: no text in the directive
    assert out["doc_ids"] == ["c1", "c2"]  # all docs → ONE dispatch (a list)
    assert (
        tmp_path / ".brainpalace" / "state" / "last-drain"
    ).exists()  # E3 stamp-on-emit


def test_unified_drain_cooldown_blocks_renag(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "brainpalace_cli.commands.extraction_drain._fetch_pending",
        lambda url, timeout: {
            "items": [{"source": "doc", "id": "c1", "text": "x"}],
            "doc_pending_total": 1,
        },
    )
    (tmp_path / ".brainpalace" / "state").mkdir(parents=True)
    (tmp_path / ".brainpalace" / "state" / "last-drain").write_text("1000.0")
    out = unified_drain(
        tmp_path,
        url="http://x",
        doc_cap=3,
        session_budget=10**9,
        session_cap=3,
        cooldown=300,
        now=1100.0,
    )  # within cooldown
    assert out["directive"] is None


def test_unified_drain_failopen_on_error(tmp_path, monkeypatch):
    def boom(url, timeout):
        raise OSError("server down")

    monkeypatch.setattr(
        "brainpalace_cli.commands.extraction_drain._fetch_pending", boom
    )
    assert (
        unified_drain(
            tmp_path,
            url="http://x",
            doc_cap=3,
            session_budget=1,
            session_cap=3,
            cooldown=0,
            now=1.0,
        )["directive"]
        is None
    )


def test_unified_drain_paused_indexing_note_present_when_at_or_above_max(
    tmp_path, monkeypatch
):
    pending = {
        "items": [{"source": "doc", "id": "c1", "text": "x"}],
        "doc_pending_total": 50,
    }
    monkeypatch.setattr(
        "brainpalace_cli.commands.extraction_drain._fetch_pending",
        lambda url, timeout: pending,
    )
    out = unified_drain(
        tmp_path,
        url="http://x",
        doc_cap=4,
        session_budget=10**9,
        session_cap=2,
        cooldown=0,
        max_pending=50,
        now=1000.0,
    )
    d = out["directive"]
    assert "indexing is paused" in d
    assert "50 chunks queued" in d


def test_unified_drain_paused_indexing_note_absent_when_under_max(
    tmp_path, monkeypatch
):
    pending = {
        "items": [{"source": "doc", "id": "c1", "text": "x"}],
        "doc_pending_total": 49,
    }
    monkeypatch.setattr(
        "brainpalace_cli.commands.extraction_drain._fetch_pending",
        lambda url, timeout: pending,
    )
    out = unified_drain(
        tmp_path,
        url="http://x",
        doc_cap=4,
        session_budget=10**9,
        session_cap=2,
        cooldown=0,
        max_pending=50,
        now=1000.0,
    )
    d = out["directive"]
    assert d is not None
    assert "indexing is paused" not in d
