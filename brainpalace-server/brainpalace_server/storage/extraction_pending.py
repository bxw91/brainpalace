"""SQLite per-chunk pending queue for deferred graph extraction (Plan 2).

At index time doc chunks are marked pending here (not extracted inline — spec
§8); the reconciler drains them. Content-hash dedup means re-indexing an
unchanged chunk is a no-op while an edited chunk re-queues (per-chunk resume,
spec §6/§15.4). A ``done`` row is deleted, so the table only ever holds the
un-drained backlog.

Thread-safety: a single connection is shared across the indexer thread
(``mark_pending``), the reconciler's event loop (``select_pending``/``mark_done``)
and FastAPI request handlers (``/extraction/*``). ``check_same_thread=False``
permits that, but SQLite/`sqlite3` give no write serialization for a shared
connection, so every method takes ``self._lock`` (finding 2-2).
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path

_SEEN = "seen"  # processed once; row kept only to remember the content hash
_PENDING = "pending"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocPendingStore:
    """Per-chunk pending/seen queue keyed by ``chunk_id`` (thread-safe)."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Serialize every access to the shared connection (finding 2-2). SQLite's
        # own locking is per-connection; concurrent writes from >1 thread on the
        # same connection object can raise/interleave without this.
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS doc_pending ("
            " chunk_id TEXT PRIMARY KEY,"
            " text TEXT NOT NULL,"
            " content_hash TEXT NOT NULL,"
            " status TEXT NOT NULL,"
            " kind TEXT NOT NULL DEFAULT 'doc',"
            " created_at REAL NOT NULL)"
        )
        # Migrate pre-`kind` tables (existing backlogs predate the source split):
        # add the column defaulted to 'doc' so old rows stay countable.
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(doc_pending)")}
        if "kind" not in cols:
            self._conn.execute(
                "ALTER TABLE doc_pending ADD COLUMN kind TEXT NOT NULL DEFAULT 'doc'"
            )
        self._conn.commit()

    def mark_pending(self, chunk_id: str, text: str, kind: str = "doc") -> None:
        h = _hash(text)
        with self._lock:
            row = self._conn.execute(
                "SELECT content_hash, status FROM doc_pending WHERE chunk_id=?",
                (chunk_id,),
            ).fetchone()
            if row is not None and row[0] == h and row[1] == _SEEN:
                return  # unchanged + already processed ⇒ no re-queue
            self._conn.execute(
                "INSERT INTO doc_pending"
                "(chunk_id, text, content_hash, status, kind, created_at)"
                " VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(chunk_id) DO UPDATE SET"
                " text=excluded.text, content_hash=excluded.content_hash,"
                " status=excluded.status, kind=excluded.kind,"
                " created_at=excluded.created_at",
                (chunk_id, text, h, _PENDING, kind, time.time()),
            )
            self._conn.commit()

    def select_pending(self, limit: int) -> list[tuple[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT chunk_id, text FROM doc_pending WHERE status=?"
                " ORDER BY created_at ASC LIMIT ?",
                (_PENDING, limit),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def select_pending_older_than(
        self, age_seconds: float, limit: int
    ) -> list[tuple[str, str]]:
        """Pending chunks whose ``created_at`` is older than ``age_seconds`` ago.

        Backs the Plan 4 ``auto``-mode grace window: the paid provider only mops
        up chunks the free subagent left past the grace cutoff (H1).
        """
        cutoff = time.time() - age_seconds
        with self._lock:
            rows = self._conn.execute(
                "SELECT chunk_id, text FROM doc_pending WHERE status=?"
                " AND created_at < ? ORDER BY created_at ASC LIMIT ?",
                (_PENDING, cutoff, limit),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def mark_done(self, chunk_id: str) -> None:
        # Keep the row (status=seen) so an unchanged re-index does not re-queue,
        # but drop the (potentially large) text — only the hash is needed now.
        with self._lock:
            self._conn.execute(
                "UPDATE doc_pending SET status=?, text='' WHERE chunk_id=?",
                (_SEEN, chunk_id),
            )
            self._conn.commit()

    def get_text(self, chunk_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT text FROM doc_pending WHERE chunk_id=? AND status=?",
                (chunk_id, _PENDING),
            ).fetchone()
        return row[0] if row is not None else None

    def count_pending(self, kind: str | None = None) -> int:
        """Pending count, optionally filtered to one ``kind`` (``doc``/``git``).
        ``None`` counts every kind (back-compat)."""
        with self._lock:
            if kind is None:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM doc_pending WHERE status=?", (_PENDING,)
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM doc_pending WHERE status=? AND kind=?",
                    (_PENDING, kind),
                ).fetchone()
        return int(row[0]) if row else 0
