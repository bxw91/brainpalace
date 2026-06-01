"""SQLite-backed property-graph store (Phase 090).

A persistent, incrementally-writable graph backend that duck-types the subset of
the llama_index ``PropertyGraphStore`` surface the rest of the codebase consumes
(:meth:`get`, :meth:`get_triplets`, :meth:`upsert_nodes`,
:meth:`upsert_relations`, :meth:`persist`, :meth:`from_persist_path`,
:meth:`clear`) so :mod:`brainpalace_server.indexing.graph_index` and
:class:`~brainpalace_server.storage.graph_store.GraphStoreManager` work against it
unchanged.

Unlike ``SimplePropertyGraphStore`` (in-memory dict serialized to a whole JSON
file on every persist), this store writes each triplet incrementally to a
``sqlite3`` database and loads bounded slices on read.

On top of the property-graph surface it adds a **temporal-validity model**
(MemPalace-inspired, ADR 0002): every edge carries ``valid_from`` / ``valid_until``
columns, can be :meth:`invalidate`\\d, and can be queried ``as_of`` a point in time
or across its full :meth:`timeline`. ``get_triplets`` returns only currently-valid
edges by default, so GRAPH retrieval is identical to the ``simple`` backend.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from llama_index.core.graph_stores.types import EntityNode, Relation

_SEP = "\x1f"  # unit separator — safe edge-id delimiter
SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_iso(ts: datetime | str | None) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def _edge_id(source_id: str, label: str, target_id: str) -> str:
    return f"{source_id}{_SEP}{label}{_SEP}{target_id}"


class SQLitePropertyGraphStore:
    """A property-graph store backed by SQLite with temporal validity."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # ------------------------------------------------------------------ schema
    def _init_schema(self) -> None:
        cur = self._conn
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                label      TEXT,
                properties TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_name
                ON nodes (name COLLATE NOCASE);

            CREATE TABLE IF NOT EXISTS edges (
                id          TEXT PRIMARY KEY,
                source_id   TEXT NOT NULL,
                target_id   TEXT NOT NULL,
                label       TEXT,
                properties  TEXT,
                valid_from  TEXT,
                valid_until TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges (source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges (target_id);
            CREATE INDEX IF NOT EXISTS idx_edges_label  ON edges (label);

            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ writes
    def upsert_nodes(self, nodes: Any) -> None:
        rows = [
            (
                n.id,
                n.name,
                getattr(n, "label", None),
                json.dumps(dict(getattr(n, "properties", {}) or {}), default=str),
            )
            for n in nodes
        ]
        self._conn.executemany(
            """
            INSERT INTO nodes (id, name, label, properties)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                label = excluded.label,
                properties = excluded.properties
            """,
            rows,
        )
        self._conn.commit()

    def upsert_relations(self, relations: Any) -> None:
        for r in relations:
            props = dict(getattr(r, "properties", {}) or {})
            # Pull temporal fields out of properties (migration replays carry
            # them); new edges default to now / open.
            valid_from = _to_iso(props.pop("valid_from", None)) or _now_iso()
            valid_until = _to_iso(props.pop("valid_until", None))
            eid = _edge_id(r.source_id, r.label, r.target_id)
            self._conn.execute(
                """
                INSERT INTO edges
                    (id, source_id, target_id, label, properties,
                     valid_from, valid_until)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    properties = excluded.properties
                """,
                (
                    eid,
                    r.source_id,
                    r.target_id,
                    r.label,
                    json.dumps(props, default=str),
                    valid_from,
                    valid_until,
                ),
            )
        self._conn.commit()

    # ------------------------------------------------------------------- reads
    def get(
        self,
        properties: dict[str, Any] | None = None,
        ids: list[str] | None = None,
    ) -> list[EntityNode]:
        sql = "SELECT id, name, label, properties FROM nodes"
        params: list[Any] = []
        if ids:
            placeholders = ",".join("?" * len(ids))
            sql += f" WHERE id IN ({placeholders})"
            params.extend(ids)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_node(row) for row in rows]

    def get_triplets(
        self,
        entity_names: list[str] | None = None,
        relation_names: list[str] | None = None,
        properties: dict[str, Any] | None = None,
        ids: list[str] | None = None,
        *,
        as_of: datetime | str | None = None,
        include_invalid: bool = False,
    ) -> list[tuple[EntityNode, Relation, EntityNode]]:
        # llama_index semantics: a bare get_triplets (no entity filter) returns
        # nothing meaningful for our callers; they always pass entity_names.
        if not entity_names:
            return []

        node_ids = self._ids_for_names(entity_names)
        if not node_ids:
            return []

        placeholders = ",".join("?" * len(node_ids))
        sql = (
            "SELECT id, source_id, target_id, label, properties, "
            "valid_from, valid_until FROM edges "
            f"WHERE (source_id IN ({placeholders}) OR target_id IN ({placeholders}))"
        )
        params: list[Any] = [*node_ids, *node_ids]
        sql, params = self._apply_temporal(sql, params, as_of, include_invalid)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_triplet(row) for row in rows]

    def clear(self) -> None:
        self._conn.executescript("DELETE FROM nodes; DELETE FROM edges;")
        self._conn.commit()

    # --------------------------------------------------------------- temporal
    def invalidate(
        self,
        subject: str,
        predicate: str,
        obj: str,
        at: datetime | str | None = None,
    ) -> int:
        """Close an open edge. Returns the number of edges invalidated."""
        sid = self._id_for_name(subject)
        tid = self._id_for_name(obj)
        if sid is None or tid is None:
            return 0
        eid = _edge_id(sid, predicate, tid)
        cur = self._conn.execute(
            "UPDATE edges SET valid_until = ? " "WHERE id = ? AND valid_until IS NULL",
            (_to_iso(at) or _now_iso(), eid),
        )
        self._conn.commit()
        return cur.rowcount

    def timeline(self, entity_name: str) -> list[dict[str, Any]]:
        """All edges touching the entity, ordered by ``valid_from``."""
        node_id = self._id_for_name(entity_name)
        if node_id is None:
            return []
        rows = self._conn.execute(
            "SELECT id, source_id, target_id, label, properties, "
            "valid_from, valid_until FROM edges "
            "WHERE source_id = ? OR target_id = ? ORDER BY valid_from",
            (node_id, node_id),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "subject": row["source_id"],
                    "predicate": row["label"],
                    "object": row["target_id"],
                    "valid_from": row["valid_from"],
                    "valid_until": row["valid_until"],
                    "valid": row["valid_until"] is None,
                }
            )
        return out

    def find_decision_nodes(self, text: str) -> list[str]:
        """Names of ``Decision`` nodes matching ``text`` (case-insensitive).

        Conservative exact-match on normalised text (Phase 140) — never
        substring, to avoid wrongly resolving a supersession target.
        """
        rows = self._conn.execute(
            "SELECT name FROM nodes WHERE label = 'Decision' "
            "AND name = ? COLLATE NOCASE",
            (text.strip(),),
        ).fetchall()
        return [r["name"] for r in rows]

    # ----------------------------------------------------------------- counts
    def node_count(self) -> int:
        return int(self._conn.execute("SELECT count(*) FROM nodes").fetchone()[0])

    def edge_count(self, include_invalid: bool = False) -> int:
        sql = "SELECT count(*) FROM edges"
        if not include_invalid:
            sql += " WHERE valid_until IS NULL"
        return int(self._conn.execute(sql).fetchone()[0])

    # ------------------------------------------------------------ persistence
    def persist(self, persist_path: str | None = None, fs: Any = None) -> None:
        """Flush pending writes. The DB file *is* the persistence."""
        self._conn.commit()

    @classmethod
    def from_persist_path(
        cls, persist_path: str, fs: Any = None
    ) -> SQLitePropertyGraphStore:
        return cls(persist_path)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------- internals
    def _apply_temporal(
        self,
        sql: str,
        params: list[Any],
        as_of: datetime | str | None,
        include_invalid: bool,
    ) -> tuple[str, list[Any]]:
        if as_of is not None:
            ts = _to_iso(as_of)
            sql += " AND valid_from <= ? AND (valid_until IS NULL OR valid_until > ?)"
            params.extend([ts, ts])
        elif not include_invalid:
            sql += " AND valid_until IS NULL"
        return sql, params

    def _ids_for_names(self, names: list[str]) -> list[str]:
        placeholders = ",".join("?" * len(names))
        rows = self._conn.execute(
            f"SELECT id FROM nodes WHERE name IN ({placeholders}) COLLATE NOCASE",
            names,
        ).fetchall()
        return [row["id"] for row in rows]

    def _id_for_name(self, name: str) -> str | None:
        row = self._conn.execute(
            "SELECT id FROM nodes WHERE name = ? COLLATE NOCASE LIMIT 1",
            (name,),
        ).fetchone()
        return row["id"] if row else None

    def _row_to_node(self, row: sqlite3.Row) -> EntityNode:
        props = json.loads(row["properties"]) if row["properties"] else {}
        return EntityNode(
            name=row["name"], label=row["label"] or "Entity", properties=props
        )

    def _node_for_id(self, node_id: str) -> EntityNode:
        row = self._conn.execute(
            "SELECT id, name, label, properties FROM nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            return EntityNode(name=node_id, label="Entity")
        return self._row_to_node(row)

    def _row_to_triplet(
        self, row: sqlite3.Row
    ) -> tuple[EntityNode, Relation, EntityNode]:
        props = json.loads(row["properties"]) if row["properties"] else {}
        # Round-trip temporal fields back into properties so consumers that
        # round-trip a Relation keep them.
        props.setdefault("valid_from", row["valid_from"])
        if row["valid_until"] is not None:
            props.setdefault("valid_until", row["valid_until"])
        subj = self._node_for_id(row["source_id"])
        obj = self._node_for_id(row["target_id"])
        rel = Relation(
            label=row["label"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            properties=props,
        )
        return (subj, rel, obj)
