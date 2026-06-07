"""Per-project SQLite log of queries + truncated results.

A small, dependency-free store backing the dashboard "Queries" tab. Each
successful query is recorded fire-and-forget after it runs (see
``api/routers/query.py``); the list view omits the result payload and the
detail view returns the slim per-result rows. Retention is enforced by
``purge`` on server startup (``retention_days <= 0`` keeps everything).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    mode TEXT NOT NULL,
    query TEXT NOT NULL,
    top_k INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    result_count INTEGER NOT NULL,
    alpha REAL,
    filters_json TEXT,
    results_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_queries_ts ON queries(ts);
CREATE INDEX IF NOT EXISTS idx_queries_mode ON queries(mode);
"""


class QueryLogService:
    """SQLite-backed query history store.

    Attributes ``enabled`` and ``retention_days`` are set by the server
    lifespan from config; the write helper in the query router checks
    ``enabled`` before recording.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        enabled: bool = True,
        retention_days: int = 7,
    ) -> None:
        self.db_path = Path(db_path)
        self.enabled = enabled
        self.retention_days = retention_days
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def record(
        self,
        *,
        query: str,
        mode: str,
        top_k: int,
        latency_ms: float,
        results: list[dict[str, Any]],
        alpha: float | None = None,
        filters: dict[str, Any] | None = None,
        ts: float | None = None,
    ) -> str:
        """Insert one query row (with truncated results) and return its id."""
        qid = uuid.uuid4().hex
        slim = [
            {
                "score": r.get("score"),
                "path": r.get("path"),
                "lines": r.get("lines"),
                "snippet": (r.get("snippet") or "")[:500],
            }
            for r in results[:top_k]
        ]
        with self._conn() as c:
            c.execute(
                "INSERT INTO queries (id, ts, mode, query, top_k, latency_ms, "
                "result_count, alpha, filters_json, results_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    qid,
                    ts if ts is not None else time.time(),
                    mode,
                    query,
                    top_k,
                    latency_ms,
                    len(results),
                    alpha,
                    json.dumps(filters or {}),
                    json.dumps(slim),
                ),
            )
        return qid

    def list_recent(
        self,
        *,
        since: float | None = None,
        mode: str | None = None,
        contains: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return recent query rows (newest first) WITHOUT the result payload."""
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)
        if mode:
            clauses.append("mode = ?")
            params.append(mode)
        if contains:
            clauses.append("query LIKE ?")
            params.append(f"%{contains}%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT id, ts, mode, query, top_k, latency_ms, result_count, alpha "
            f"FROM queries{where} ORDER BY ts DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def get(self, qid: str) -> dict[str, Any] | None:
        """Return a single query row including the truncated results payload."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM queries WHERE id = ?", (qid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["results"] = json.loads(d.pop("results_json") or "[]")
        d["filters"] = json.loads(d.pop("filters_json") or "{}")
        return d

    def purge(self, retention_days: int) -> int:
        """Delete rows older than ``retention_days``. ``<= 0`` keeps forever."""
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400
        with self._conn() as c:
            cur = c.execute("DELETE FROM queries WHERE ts < ?", (cutoff,))
            return cur.rowcount
