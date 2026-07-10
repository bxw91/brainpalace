"""Lazy-tier reference catalog (Phase 6, Option A1): pointer + summary for
sources fetched-and-extracted on demand. SQLite-only (records-adjacent, C4)
— mirrors RecordStore connect/PRAGMA/idempotent-migration. summary_embedding
is nullable and unwired until the first real lazy source (P2)."""

from __future__ import annotations

import builtins
import hashlib
import json
import math
import sqlite3
import struct
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict


def ref_id(pointer: str, source: str) -> str:
    return hashlib.sha1(f"{source}|{pointer}".encode()).hexdigest()[:16]


class ReferenceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    domain: str
    source: str
    source_id: str
    pointer: str
    summary: str = ""
    ingested_at: str | None = None
    properties: dict[str, str] = {}
    sensitivity: str = "normal"


_INSERT_SQL = """INSERT INTO reference_catalog
    (id,domain,source,source_id,pointer,summary,summary_embedding,ingested_at,properties,sensitivity)
    VALUES (?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET
      domain=excluded.domain, source=excluded.source, source_id=excluded.source_id,
      pointer=excluded.pointer, summary=excluded.summary,
      ingested_at=excluded.ingested_at, properties=excluded.properties,
      sensitivity=excluded.sensitivity"""


class ReferenceCatalogStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reference_catalog (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                source TEXT, source_id TEXT,
                pointer TEXT NOT NULL,
                summary TEXT,
                summary_embedding BLOB,
                ingested_at TEXT,
                properties TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_refcat_domain ON reference_catalog(domain);
            CREATE INDEX IF NOT EXISTS idx_refcat_source ON reference_catalog(source);
            """
        )
        self._conn.commit()
        # Idempotent migration: add sensitivity column to existing DBs that
        # lack it (mirrors sqlite_graph_store's domain-column migration).
        cols = {
            r[1]
            for r in self._conn.execute(
                "PRAGMA table_info(reference_catalog)"
            ).fetchall()
        }
        if "sensitivity" not in cols:
            self._conn.execute(
                "ALTER TABLE reference_catalog ADD COLUMN sensitivity TEXT "
                "NOT NULL DEFAULT 'normal'"
            )
            self._conn.commit()

    @staticmethod
    def _to_row(r: ReferenceEntry) -> tuple[object, ...]:
        return (
            r.id,
            r.domain,
            r.source,
            r.source_id,
            r.pointer,
            r.summary,
            None,
            r.ingested_at,
            json.dumps(r.properties or {}),
            r.sensitivity,
        )

    def upsert(self, refs: Iterable[ReferenceEntry]) -> int:
        rows = [self._to_row(r) for r in refs]
        with self._conn:
            self._conn.executemany(_INSERT_SQL, rows)
        return len(rows)

    def replace_source(self, source_id: str, refs: Iterable[ReferenceEntry]) -> int:
        rows = [self._to_row(r) for r in refs]
        with self._conn:
            self._conn.execute(
                "DELETE FROM reference_catalog WHERE source_id = ?", (source_id,)
            )
            self._conn.executemany(_INSERT_SQL, rows)
        return len(rows)

    def delete_by_source(self, source_id: str) -> int:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM reference_catalog WHERE source_id = ?", (source_id,)
            )
        return cur.rowcount

    def list(self, domain: str | None = None) -> list[ReferenceEntry]:
        sql = (
            "SELECT id,domain,source,source_id,pointer,summary,ingested_at,"
            "properties,sensitivity FROM reference_catalog"
        )
        params: tuple[object, ...] = ()
        if domain is not None:
            sql += " WHERE domain = ?"
            params = (domain,)
        out: list[ReferenceEntry] = []
        for row in self._conn.execute(sql, params):
            out.append(
                ReferenceEntry(
                    id=row[0],
                    domain=row[1],
                    source=row[2],
                    source_id=row[3],
                    pointer=row[4],
                    summary=row[5] or "",
                    ingested_at=row[6],
                    properties=json.loads(row[7]) if row[7] else {},
                    sensitivity=row[8],
                )
            )
        return out

    def search_summaries(
        self,
        query_embedding: builtins.list[float],
        top_k: int = 5,
        domain: str | None = None,
        include_sensitive: bool = False,
    ) -> builtins.list[tuple[ReferenceEntry, float]]:
        """Brute-force cosine search over embedded reference summaries.

        Scans every row with a non-NULL ``summary_embedding`` (the float32
        BLOBs written by :meth:`set_embeddings`), computes pure-Python cosine
        similarity against ``query_embedding``, and returns the top ``top_k``
        as ``(entry, score)`` sorted by descending similarity.

        Rows whose ``sensitivity`` is not ``"normal"`` are excluded unless
        ``include_sensitive=True``; ``domain`` filters by domain when given;
        unembedded rows are never returned.

        Complexity is O(N) in the number of embedded rows (no ANN index) —
        acceptable at the household scale this catalog targets. The spec
        documents a ~50k-row ceiling before this linear scan needs replacing
        with a vector index.
        """
        sql = (
            "SELECT id,domain,source,source_id,pointer,summary,ingested_at,"
            "properties,sensitivity,summary_embedding FROM reference_catalog"
            " WHERE summary_embedding IS NOT NULL"
        )
        params: builtins.list[object] = []
        if domain is not None:
            sql += " AND domain = ?"
            params.append(domain)
        if not include_sensitive:
            sql += " AND sensitivity = 'normal'"

        q = query_embedding
        q_norm = math.sqrt(sum(x * x for x in q))
        scored: builtins.list[tuple[ReferenceEntry, float]] = []
        for row in self._conn.execute(sql, tuple(params)):
            blob = row[9]
            dims = len(blob) // 4
            vec = struct.unpack(f"{dims}f", blob)
            v_norm = math.sqrt(sum(x * x for x in vec))
            if q_norm == 0.0 or v_norm == 0.0:
                score = 0.0
            else:
                dot = sum(a * b for a, b in zip(q, vec))
                score = dot / (q_norm * v_norm)
            entry = ReferenceEntry(
                id=row[0],
                domain=row[1],
                source=row[2],
                source_id=row[3],
                pointer=row[4],
                summary=row[5] or "",
                ingested_at=row[6],
                properties=json.loads(row[7]) if row[7] else {},
                sensitivity=row[8],
            )
            scored.append((entry, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    def resolve(self, id: str) -> str | None:
        row = self._conn.execute(
            "SELECT pointer FROM reference_catalog WHERE id = ?", (id,)
        ).fetchone()
        return row[0] if row else None

    def count(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) FROM reference_catalog").fetchone()[0]
        )

    def unembedded_entries(self) -> builtins.list[ReferenceEntry]:
        """Rows lacking a ``summary_embedding`` — the backfill work list for
        ``references embed-missing``. Carries each entry's id + summary so the
        caller can embed the summaries and re-attach via ``set_embeddings``."""
        sql = (
            "SELECT id,domain,source,source_id,pointer,summary,ingested_at,"
            "properties,sensitivity FROM reference_catalog"
            " WHERE summary_embedding IS NULL"
        )
        out: builtins.list[ReferenceEntry] = []
        for row in self._conn.execute(sql):
            out.append(
                ReferenceEntry(
                    id=row[0],
                    domain=row[1],
                    source=row[2],
                    source_id=row[3],
                    pointer=row[4],
                    summary=row[5] or "",
                    ingested_at=row[6],
                    properties=json.loads(row[7]) if row[7] else {},
                    sensitivity=row[8],
                )
            )
        return out

    def count_unembedded(self) -> int:
        return int(
            self._conn.execute(
                "SELECT COUNT(*) FROM reference_catalog"
                " WHERE summary_embedding IS NULL"
            ).fetchone()[0]
        )

    def set_embeddings(
        self, pairs: builtins.list[tuple[str, builtins.list[float]]]
    ) -> int:
        """Attach embeddings to existing rows by id. A direct UPDATE — NOT
        folded into the upsert's ON CONFLICT clause, so a summary re-upsert
        (e.g. a refresh without an embedder bound) never clobbers a
        previously-stored embedding with NULL."""
        n = 0
        with self._conn:
            for ref_id_, vec in pairs:
                blob = struct.pack(f"{len(vec)}f", *vec)
                cur = self._conn.execute(
                    "UPDATE reference_catalog SET summary_embedding = ?"
                    " WHERE id = ?",
                    (blob, ref_id_),
                )
                n += cur.rowcount
        return n
