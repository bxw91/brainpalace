"""Durable store for taught confidence rules (Phase 5 / CO-3).

Persists the declarative predicates that `register_validator` would otherwise
hold only in memory: they survive restart, are owned/versioned/soft-retired.
Mirrors RecordStore (own WAL SQLite file in the project state dir).
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_TIERS = {"HIGH", "PROVISIONAL", "UNVERIFIED"}
_COLS = (
    "id",
    "owner",
    "version",
    "metric",
    "unit",
    "value_min",
    "value_max",
    "tier",
    "created_at",
    "retired_at",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rule_id(
    owner: str,
    metric: str,
    unit: str | None,
    value_min: float | None,
    value_max: float | None,
    tier: str,
) -> str:
    key = "|".join(
        "" if p is None else str(p)
        for p in (owner, metric, unit, value_min, value_max, tier)
    )
    return hashlib.sha1(key.encode()).hexdigest()[:16]


class TaughtRuleStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS taught_rules (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                version INTEGER NOT NULL,
                metric TEXT NOT NULL,
                unit TEXT,
                value_min REAL,
                value_max REAL,
                tier TEXT NOT NULL,
                definition TEXT NOT NULL,
                created_at TEXT NOT NULL,
                retired_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_taught_rules_active
                ON taught_rules(retired_at, metric);
            """
        )
        self._conn.commit()

    def add_rule(
        self,
        *,
        owner: str,
        metric: str,
        tier: str,
        unit: str | None = None,
        value_min: float | None = None,
        value_max: float | None = None,
    ) -> str:
        if tier not in _TIERS:
            raise ValueError(f"unsupported tier: {tier!r}")
        if value_min is not None and value_max is not None and value_min > value_max:
            raise ValueError("value_min must be <= value_max")
        rid = _rule_id(owner, metric, unit, value_min, value_max, tier)
        now = _now()
        with self._conn:
            # Finding C: enforce one active rule per (owner, metric, unit).
            # Retire every active sibling on this key EXCEPT the one we're about
            # to (re)activate, so an edit replaces rather than unions.
            self._conn.execute(
                "UPDATE taught_rules SET retired_at=? "
                "WHERE owner=? AND metric=? "
                "AND ((unit IS NULL AND ? IS NULL) OR unit=?) "
                "AND retired_at IS NULL AND id<>?",
                (now, owner, metric, unit, unit, rid),
            )
            existing = self.get_rule(rid)
            if existing is not None:
                # same predicate re-added: reactivate if retired, else no-op.
                self._conn.execute(
                    "UPDATE taught_rules SET retired_at=NULL WHERE id=?", (rid,)
                )
                return rid
            maxv = self._conn.execute(
                "SELECT MAX(version) FROM taught_rules WHERE owner=? AND metric=?",
                (owner, metric),
            ).fetchone()[0]
            version = (maxv or 0) + 1
            import json

            definition = json.dumps(
                {
                    "metric": metric,
                    "unit": unit,
                    "value_min": value_min,
                    "value_max": value_max,
                    "tier": tier,
                }
            )
            self._conn.execute(
                "INSERT INTO taught_rules "
                "(id,owner,version,metric,unit,value_min,value_max,tier,"
                "definition,created_at,retired_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    rid,
                    owner,
                    version,
                    metric,
                    unit,
                    value_min,
                    value_max,
                    tier,
                    definition,
                    now,
                ),
            )
        return rid

    def retire_rule(self, rule_id: str) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE taught_rules SET retired_at=? "
                "WHERE id=? AND retired_at IS NULL",
                (_now(), rule_id),
            )
        return cur.rowcount > 0

    def _row_to_dict(self, row: tuple[object, ...]) -> dict[str, object]:
        return dict(zip(_COLS, row))

    def list_rules(self, active_only: bool = True) -> list[dict[str, object]]:
        sql = f"SELECT {','.join(_COLS)} FROM taught_rules"
        if active_only:
            sql += " WHERE retired_at IS NULL"
        sql += " ORDER BY metric, version"
        return [self._row_to_dict(r) for r in self._conn.execute(sql).fetchall()]

    def get_rule(self, rule_id: str) -> dict[str, object] | None:
        row = self._conn.execute(
            f"SELECT {','.join(_COLS)} FROM taught_rules WHERE id=?", (rule_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None
