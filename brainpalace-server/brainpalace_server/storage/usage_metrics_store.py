"""Isolated telemetry store for usage/spend counters (own sqlite file).

Mirrors record_store's sqlite/WAL+busy_timeout pattern. Additive **per-minute**
counters (chunks/calls/triplets/tokens/cache/errors) + an overwrite gauge for
queue depth. No user-facing data — pure internal telemetry (spec approach A).

Buckets are minutes (``unixtime // 60``) so short windows show intra-hour
shape; the read side (``aggregate``) downsamples to a coarser bucket size for
long windows so the chart stays readable.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

# v2: time buckets are minutes (was hours in v1). The upgrade path wipes the
# old hourly rows — telemetry counters are disposable, never user data.
_SCHEMA_VERSION = 2

_INSERT_SQL = """INSERT INTO usage_metrics
    (bucket,channel,provider,model,source,
     chunks,calls,triplets,tokens_in,tokens_out,cache_read,cache_write,errors)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(bucket,channel,provider,model,source) DO UPDATE SET
      chunks=chunks+excluded.chunks, calls=calls+excluded.calls,
      triplets=triplets+excluded.triplets,
      tokens_in=tokens_in+excluded.tokens_in,
      tokens_out=tokens_out+excluded.tokens_out,
      cache_read=cache_read+excluded.cache_read,
      cache_write=cache_write+excluded.cache_write,
      errors=errors+excluded.errors"""

_COUNT_COLS = (
    "chunks",
    "calls",
    "triplets",
    "tokens_in",
    "tokens_out",
    "cache_read",
    "cache_write",
    "errors",
)


class UsageMetricsStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version and version < _SCHEMA_VERSION:
            # Disposable counters — drop and recreate rather than migrate.
            self._conn.executescript(
                "DROP TABLE IF EXISTS usage_metrics;"
                "DROP TABLE IF EXISTS usage_queue_samples;"
            )
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS usage_metrics (
                bucket INT NOT NULL, channel TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'unknown',
                chunks INT NOT NULL DEFAULT 0, calls INT NOT NULL DEFAULT 0,
                triplets INT NOT NULL DEFAULT 0,
                tokens_in INT NOT NULL DEFAULT 0, tokens_out INT NOT NULL DEFAULT 0,
                cache_read INT NOT NULL DEFAULT 0, cache_write INT NOT NULL DEFAULT 0,
                errors INT NOT NULL DEFAULT 0,
                PRIMARY KEY (bucket,channel,provider,model,source)
            );
            CREATE INDEX IF NOT EXISTS idx_usage_bucket ON usage_metrics(bucket);
            CREATE TABLE IF NOT EXISTS usage_queue_samples (
                bucket INT NOT NULL, source TEXT NOT NULL,
                depth INT NOT NULL DEFAULT 0, sampled_at INT NOT NULL DEFAULT 0,
                PRIMARY KEY (bucket,source)
            );
            """
        )
        self._conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        self._conn.commit()

    def record(
        self,
        bucket: int,
        channel: str,
        provider: str,
        model: str,
        source: str,
        *,
        chunks: int = 0,
        calls: int = 0,
        triplets: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
        errors: int = 0,
    ) -> None:
        with self._conn:
            self._conn.execute(
                _INSERT_SQL,
                (
                    int(bucket),
                    channel,
                    provider or "",
                    model or "",
                    source or "unknown",
                    chunks,
                    calls,
                    triplets,
                    tokens_in,
                    tokens_out,
                    cache_read,
                    cache_write,
                    errors,
                ),
            )

    def sample_queue(
        self, bucket: int, source: str, depth: int, sampled_at: int
    ) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO usage_queue_samples (bucket,source,depth,sampled_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(bucket,source) DO UPDATE SET
                     depth=excluded.depth, sampled_at=excluded.sampled_at""",
                (int(bucket), source, int(depth), int(sampled_at)),
            )

    def latest_bucket(self) -> int | None:
        """Minute bucket of the most recent recorded metric, or ``None``.

        Lets the endpoint anchor a window to the newest data instead of
        wall-clock now, so a quiet hour still shows the last recorded hour.
        """
        row = self._conn.execute("SELECT MAX(bucket) FROM usage_metrics").fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def aggregate(
        self, since_bucket: int, bucket_size: int = 1
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return (totals, series).

        ``totals`` sums every counter over the window. ``series`` is the
        per-time-bucket trend, downsampled to ``bucket_size`` minutes (1 =
        finest, one row per minute that had activity). Tokens are split by
        channel (§6-F7); ``bucket`` on each series row is the group-start
        minute index (unix minutes).
        """
        size = max(1, int(bucket_size))
        sums = ",".join("SUM(" + c + ")" for c in _COUNT_COLS)
        cur = self._conn.execute(
            f"SELECT channel,provider,model,source,{sums}"
            " FROM usage_metrics WHERE bucket >= ?"
            " GROUP BY channel,provider,model,source",
            (since_bucket,),
        )
        totals = [
            {
                "channel": r[0],
                "provider": r[1],
                "model": r[2],
                "source": r[3],
                **{c: int(r[4 + i] or 0) for i, c in enumerate(_COUNT_COLS)},
            }
            for r in cur.fetchall()
        ]
        # series: each token MEASURE kept separate, split by channel (§6-F7) —
        # one graphable column per type (sent / received / cache-read /
        # cache-write), grouped into bucket_size-minute slots.
        cur = self._conn.execute(
            """SELECT (bucket / ?) * ? AS g, SUM(chunks), SUM(calls), SUM(triplets),
                  SUM(CASE WHEN channel='embedding' THEN tokens_in   ELSE 0 END),
                  SUM(CASE WHEN channel='embedding' THEN cache_read  ELSE 0 END),
                  SUM(CASE WHEN channel='provider'  THEN tokens_in   ELSE 0 END),
                  SUM(CASE WHEN channel='provider'  THEN tokens_out  ELSE 0 END),
                  SUM(CASE WHEN channel='provider'  THEN cache_read  ELSE 0 END),
                  SUM(CASE WHEN channel='provider'  THEN cache_write ELSE 0 END)
               FROM usage_metrics WHERE bucket >= ?
               GROUP BY g ORDER BY g""",
            (size, size, since_bucket),
        )
        series = [
            {
                "bucket": int(r[0]),
                "chunks": int(r[1] or 0),
                "calls": int(r[2] or 0),
                "triplets": int(r[3] or 0),
                "embed_tokens_in": int(r[4] or 0),
                "embed_cache_read": int(r[5] or 0),
                "llm_tokens_in": int(r[6] or 0),
                "llm_tokens_out": int(r[7] or 0),
                "llm_cache_read": int(r[8] or 0),
                "llm_cache_write": int(r[9] or 0),
            }
            for r in cur.fetchall()
        ]
        return totals, series

    def token_series_by_source(
        self, since_bucket: int, bucket_size: int = 1
    ) -> list[dict[str, Any]]:
        """Per-(time-bucket, channel, source) token measures.

        Lets the UI draw a separate trend per data source (documents, git,
        sessions, …) instead of summing them. Downsampled to ``bucket_size``
        minutes like ``aggregate``'s series.
        """
        size = max(1, int(bucket_size))
        cur = self._conn.execute(
            """SELECT (bucket / ?) * ? AS g, channel, source,
                      SUM(tokens_in), SUM(tokens_out),
                      SUM(cache_read), SUM(cache_write)
               FROM usage_metrics WHERE bucket >= ?
               GROUP BY g, channel, source ORDER BY g""",
            (size, size, since_bucket),
        )
        return [
            {
                "bucket": int(r[0]),
                "channel": r[1],
                "source": r[2],
                "tokens_in": int(r[3] or 0),
                "tokens_out": int(r[4] or 0),
                "cache_read": int(r[5] or 0),
                "cache_write": int(r[6] or 0),
            }
            for r in cur.fetchall()
        ]

    def queue_latest(self) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            """SELECT source, depth, sampled_at FROM usage_queue_samples q
               WHERE sampled_at = (SELECT MAX(sampled_at) FROM usage_queue_samples
                                   WHERE source = q.source)"""
        )
        return [
            {"source": r[0], "depth": int(r[1]), "sampled_at": int(r[2])}
            for r in cur.fetchall()
        ]

    def prune(self, now_bucket: int, retain_days: int) -> None:
        """Keep the ``retain_days`` most-recent *active* days, drop older ones.

        Retention is by **working days**, not the calendar: a day with no
        activity does not consume the budget, so an idle weekend never ages
        out real data. ``retain_days <= 0`` keeps everything forever (§6-F1).
        ``now_bucket`` is accepted for call-site symmetry but unused — the
        window is anchored to the newest recorded day, not wall-clock.
        """
        del now_bucket  # retention is anchored to recorded data, not "now"
        if retain_days <= 0:
            return  # forever (§6-F1)
        # Distinct active days (1440 min/day), newest first; keep the top N.
        active_days = [
            r[0]
            for r in self._conn.execute(
                "SELECT DISTINCT bucket / 1440 FROM usage_metrics"
                " ORDER BY 1 DESC LIMIT ?",
                (int(retain_days),),
            ).fetchall()
        ]
        if len(active_days) < int(retain_days):
            return  # fewer active days than the budget — nothing to drop
        cutoff = int(active_days[-1]) * 1440  # start of the oldest kept day
        with self._conn:
            self._conn.execute("DELETE FROM usage_metrics WHERE bucket < ?", (cutoff,))
            self._conn.execute(
                "DELETE FROM usage_queue_samples WHERE bucket < ?", (cutoff,)
            )

    def close(self) -> None:
        self._conn.close()
