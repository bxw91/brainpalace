"""Tests for DocPendingStore.get_text (Task 2 — id-based fetch)."""

import sqlite3

from brainpalace_server.storage.extraction_pending import DocPendingStore


def test_get_text_pending_then_none_after_done(tmp_path):
    s = DocPendingStore(tmp_path / "p.db")
    s.mark_pending("c1", "alpha beta")
    assert s.get_text("c1") == "alpha beta"
    assert s.get_text("missing") is None
    s.mark_done("c1")
    assert s.get_text("c1") is None  # text cleared on done (E4)


def test_count_pending_by_kind(tmp_path):
    s = DocPendingStore(tmp_path / "p.db")
    s.mark_pending("d1", "doc one", kind="doc")
    s.mark_pending("d2", "doc two", kind="doc")
    s.mark_pending("g1", "git one", kind="git")
    assert s.count_pending(kind="doc") == 2
    assert s.count_pending(kind="git") == 1
    assert s.count_pending() == 3  # unfiltered counts every kind


def test_migrates_pre_kind_table(tmp_path):
    """A legacy doc_pending table without the kind column migrates on open, and
    its existing rows count as kind='doc'."""
    db = tmp_path / "p.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE doc_pending ("
        " chunk_id TEXT PRIMARY KEY, text TEXT NOT NULL, content_hash TEXT NOT NULL,"
        " status TEXT NOT NULL, created_at REAL NOT NULL)"
    )
    conn.execute("INSERT INTO doc_pending VALUES('old', 'x', 'h', 'pending', 1.0)")
    conn.commit()
    conn.close()

    s = DocPendingStore(db)  # opens + migrates
    assert s.count_pending() == 1
    assert s.count_pending(kind="doc") == 1  # legacy rows default to 'doc'
