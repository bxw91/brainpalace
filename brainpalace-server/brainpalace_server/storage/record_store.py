"""Dedicated relational store for typed numeric Records (Phase 0/1).

Separate from the JSON graph store so aggregation is indexed column scans with
pre-derived ISO-week/month buckets — not json_extract or strftime at query.
SQLite only — no DuckDB.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from brainpalace_server.models.record import Record, RecordCandidate

_OPS = {"sum": "SUM", "count": "COUNT", "avg": "AVG", "max": "MAX", "min": "MIN"}
# group token -> plain indexed column (version-proof; no strftime at query time)
_GROUPS = {
    "week": "iso_week",
    "month": "ym",
    "source": "source",
    "subject": "subject",
    "unit": "unit",
}

# absence anti-join: only these columns may be partitioned/keyed on
# (never interpolate raw user input as a SQL identifier).
_PARTITIONS = {"metric", "source", "domain"}
_KEYS = {"subject", "source_id"}

_INSERT_SQL = """INSERT INTO records
    (id,subject,metric,value,unit,ts,iso_week,ym,domain,source,source_id,
     ingested_at,confidence,salience,properties,sensitivity)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET
      subject=excluded.subject, metric=excluded.metric, value=excluded.value,
      unit=excluded.unit, ts=excluded.ts, iso_week=excluded.iso_week,
      ym=excluded.ym, domain=excluded.domain, source=excluded.source,
      source_id=excluded.source_id, ingested_at=excluded.ingested_at,
      confidence=excluded.confidence, salience=excluded.salience,
      properties=excluded.properties, sensitivity=excluded.sensitivity"""


def derive_buckets(ts: str | None) -> tuple[str | None, str | None]:
    if not ts:
        return None, None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None, None
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}", f"{d.year}-{d.month:02d}"


class RecordStore:
    def __init__(self, db_path: str | Path) -> None:
        # check_same_thread=False + busy_timeout: mirrors the graph store so the
        # store is usable from FastAPI's threadpool (finding #6).
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY, subject TEXT NOT NULL, metric TEXT NOT NULL,
                value REAL NOT NULL, unit TEXT, ts TEXT,
                iso_week TEXT, ym TEXT,
                domain TEXT NOT NULL DEFAULT 'code',
                source TEXT, source_id TEXT, ingested_at TEXT,
                confidence REAL NOT NULL DEFAULT 0.0,
                salience REAL NOT NULL DEFAULT 0.0, properties TEXT,
                sensitivity TEXT NOT NULL DEFAULT 'normal'
            );
            CREATE INDEX IF NOT EXISTS idx_records_metric ON records(metric);
            CREATE INDEX IF NOT EXISTS idx_records_subject ON records(subject);
            """
        )
        # idempotent migration for pre-Phase-5 (and older) stores: ALTER-add any
        # column the CREATE TABLE above would define but a legacy table lacks,
        # before indexing it (mirrors the graph-store domain-column migration
        # in sqlite_graph_store.py). Indexes on these columns are created only
        # after the columns are guaranteed to exist.
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(records)")}
        for col, ddl in (
            ("domain", "TEXT NOT NULL DEFAULT 'code'"),
            ("ts", "TEXT"),
            ("source", "TEXT"),
            ("source_id", "TEXT"),
            ("salience", "REAL NOT NULL DEFAULT 0.0"),
            ("sensitivity", "TEXT NOT NULL DEFAULT 'normal'"),
        ):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE records ADD COLUMN {col} {ddl}")
        self._conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_records_domain ON records(domain);
            CREATE INDEX IF NOT EXISTS idx_records_ts ON records(ts);
            CREATE INDEX IF NOT EXISTS idx_records_source_id ON records(source_id);
            CREATE INDEX IF NOT EXISTS idx_records_source ON records(source);
            CREATE INDEX IF NOT EXISTS idx_records_salience ON records(salience);
            CREATE INDEX IF NOT EXISTS idx_records_sensitivity ON records(sensitivity);
            """
        )
        self._conn.commit()

    @staticmethod
    def _to_rows(records: Iterable[Record]) -> list[tuple[object, ...]]:
        rows: list[tuple[object, ...]] = []
        for r in records:
            iw, ym = derive_buckets(r.ts)
            rows.append(
                (
                    r.id,
                    r.subject,
                    r.metric,
                    r.value,
                    r.unit,
                    r.ts,
                    iw,
                    ym,
                    r.domain,
                    r.source,
                    r.source_id,
                    r.ingested_at,
                    r.confidence,
                    r.salience,
                    json.dumps(r.properties or {}),
                    r.sensitivity,
                )
            )
        return rows

    def insert_records(self, records: Iterable[Record]) -> int:
        rows = self._to_rows(records)
        with self._conn:  # one transaction (commit/rollback)
            self._conn.executemany(_INSERT_SQL, rows)
        return len(rows)

    def replace_source(self, source_id: str, records: Iterable[Record]) -> int:
        """Atomic delete-by-source + insert in ONE transaction — idempotent
        re-distill, no half-written state on crash (findings #5, #10)."""
        rows = self._to_rows(records)
        with self._conn:
            self._conn.execute("DELETE FROM records WHERE source_id = ?", (source_id,))
            self._conn.executemany(_INSERT_SQL, rows)
        return len(rows)

    def delete_by_source(self, source_id: str) -> int:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM records WHERE source_id = ?", (source_id,)
            )
        return cur.rowcount

    def aggregate(
        self,
        *,
        metric: str,
        op: str,
        group_by: str | None = None,
        domain: str | None = None,
        subject: str | None = None,
        since: str | None = None,
        until: str | None = None,
        min_confidence: float = 0.7,
        exclude_sources: list[str] | None = None,
        order: str = "desc",
        limit: int | None = None,
        include_sensitive: bool = False,
    ) -> list[tuple[str | None, float]]:
        if op not in _OPS:
            raise ValueError(f"unsupported op: {op!r}")
        if group_by is not None and group_by not in _GROUPS:
            raise ValueError(f"unsupported group_by: {group_by!r}")
        if order not in ("asc", "desc"):
            raise ValueError(f"unsupported order: {order!r}")
        agg = "COUNT(*)" if op == "count" else f"{_OPS[op]}(value)"
        where = ["metric = ?", "confidence >= ?"]
        params: list[object] = [metric, min_confidence]
        if domain is not None:
            where.append("domain = ?")
            params.append(domain)
        if subject is not None:
            where.append("subject = ?")
            params.append(subject)
        if since is not None:
            where.append("ts >= ?")
            params.append(since)
        if until is not None:
            where.append("ts <= ?")
            params.append(until)
        if exclude_sources:
            qs = ",".join("?" * len(exclude_sources))
            where.append(f"(source IS NULL OR source NOT IN ({qs}))")
            params.extend(exclude_sources)
        if not include_sensitive:
            where.append("sensitivity = 'normal'")
        where_sql = " AND ".join(where)
        if group_by is None:
            cur = self._conn.execute(
                f"SELECT NULL, {agg} FROM records WHERE {where_sql}", params
            )
            return [(None, float(r[1] or 0.0)) for r in cur.fetchall()]
        gexpr = _GROUPS[group_by]
        gwhere = list(where)
        if group_by in ("week", "month"):
            # an unknown/unparseable-time row is not a week/month → never let it
            # appear as a temporal group or win a superlative (finding #1).
            gwhere.append(f"{gexpr} IS NOT NULL")
        sql = (
            f"SELECT {gexpr} AS gk, {agg} AS v FROM records "
            f"WHERE {' AND '.join(gwhere)} GROUP BY gk ORDER BY v {order.upper()}"
        )
        gparams = list(params)
        if limit is not None:
            sql += " LIMIT ?"
            gparams.append(int(limit))
        cur = self._conn.execute(sql, gparams)
        return [(r[0], float(r[1] or 0.0)) for r in cur.fetchall()]

    def absent_subjects(
        self,
        *,
        partition: str,
        present_in: str,
        absent_from: str,
        key: str = "subject",
        metric: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
        min_confidence: float = 0.7,
        include_sensitive: bool = False,
    ) -> list[str]:
        """Keys present where ``partition == present_in`` but absent where
        ``partition == absent_from`` (both sides confidence-gated). Anti-join
        over indexed columns; [] when nothing qualifies."""
        if partition not in _PARTITIONS:
            raise ValueError(f"unsupported partition: {partition!r}")
        if key not in _KEYS:
            raise ValueError(f"unsupported key: {key!r}")

        def _side(value: str) -> tuple[str, list[object]]:
            where = [f"{partition} = ?", "confidence >= ?"]
            params: list[object] = [value, min_confidence]
            if metric is not None:
                where.append("metric = ?")
                params.append(metric)
            if since is not None:
                where.append("ts >= ?")
                params.append(since)
            if until is not None:
                where.append("ts < ?")
                params.append(until)
            if not include_sensitive:
                where.append("sensitivity = 'normal'")
            return " AND ".join(where), params

        lwhere, lparams = _side(present_in)
        rwhere, rparams = _side(absent_from)
        # Intentional: the anti-join filters BOTH legs by sensitivity, so a
        # subject whose only presence in `absent_from` is a sensitive row
        # reads as absent from that leg and is returned. This is correct
        # under "sensitive = invisible" — to a default viewer the sensitive
        # row does not exist, so the subject genuinely is absent. Do not
        # "fix" this by excluding the key from the anti-join subquery.
        sql = (
            f"SELECT DISTINCT {key} FROM records WHERE {lwhere} "
            f"AND {key} NOT IN (SELECT {key} FROM records WHERE {rwhere}) "
            f"ORDER BY {key}"
        )
        params = [*lparams, *rparams]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        cur = self._conn.execute(sql, params)
        return [r[0] for r in cur.fetchall() if r[0] is not None]

    def distinct_sources(self) -> list[str]:
        return [
            r[0]
            for r in self._conn.execute(
                "SELECT DISTINCT source FROM records "
                "WHERE source IS NOT NULL ORDER BY source"
            ).fetchall()
        ]

    def distinct_domains(self) -> list[str]:
        return [
            r[0]
            for r in self._conn.execute(
                "SELECT DISTINCT domain FROM records ORDER BY domain"
            ).fetchall()
        ]

    def count_unverified(self, *, min_confidence: float = 0.7) -> int:
        return int(
            self._conn.execute(
                "SELECT COUNT(*) FROM records WHERE confidence < ?",
                (min_confidence,),
            ).fetchone()[0]
        )

    def record_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    def revalidate(
        self,
        scorer: Callable[[RecordCandidate], float],
        *,
        metric: str | None = None,
        below: float = 0.7,
    ) -> int:
        where = "confidence < ?"
        params: list[object] = [below]
        if metric is not None:
            where += " AND metric = ?"
            params.append(metric)
        rows = self._conn.execute(
            f"SELECT id,subject,metric,value,unit,ts FROM records WHERE {where}",
            params,
        ).fetchall()
        n = 0
        with self._conn:
            for rid, subject, m, value, unit, ts in rows:
                cand = RecordCandidate(
                    subject=subject, metric=m, value=value, unit=unit, ts=ts
                )
                self._conn.execute(
                    "UPDATE records SET confidence=? WHERE id=?", (scorer(cand), rid)
                )
                n += 1
        return n

    def recompute_salience(
        self,
        scorer: Callable[[Record], float],
        *,
        metric: str | None = None,
    ) -> int:
        """Re-score the derived salience column (facts immutable), mirroring
        ``revalidate``. Rebuilds a full ``Record`` per row (incl. domain/source)
        so a domain-aware scorer works (Finding B). Optional ``metric`` filter.
        Returns rows re-scored."""
        where = "1=1"
        params: list[object] = []
        if metric is not None:
            where += " AND metric = ?"
            params.append(metric)
        rows = self._conn.execute(
            "SELECT id,subject,metric,value,unit,ts,domain,source,source_id,"
            f"ingested_at,confidence FROM records WHERE {where}",
            params,
        ).fetchall()
        n = 0
        with self._conn:
            for (
                rid,
                subject,
                m,
                value,
                unit,
                ts,
                domain,
                source,
                source_id,
                ingested_at,
                confidence,
            ) in rows:
                rec = Record(
                    id=rid,
                    subject=subject,
                    metric=m,
                    value=value,
                    unit=unit,
                    ts=ts,
                    domain=domain,
                    source=source,
                    source_id=source_id,
                    ingested_at=ingested_at,
                    confidence=confidence,
                )
                self._conn.execute(
                    "UPDATE records SET salience=? WHERE id=?", (scorer(rec), rid)
                )
                n += 1
        return n

    def distinct_metrics(self) -> list[str]:
        return [
            r[0]
            for r in self._conn.execute(
                "SELECT DISTINCT metric FROM records ORDER BY metric"
            ).fetchall()
        ]

    def distinct_subjects(self) -> list[str]:
        return [
            r[0]
            for r in self._conn.execute(
                "SELECT DISTINCT subject FROM records ORDER BY subject"
            ).fetchall()
        ]
