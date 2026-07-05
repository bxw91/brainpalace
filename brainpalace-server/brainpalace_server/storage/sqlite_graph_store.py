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
SCHEMA_VERSION = 2

_MAX_FRONTIER = 5000  # BFS explosion guard — search is best-effort beyond this

# Predicates whose SOURCE depends on their TARGET — the reverse closure over
# these answers "what breaks if I change X". `contains`/`modifies`/
# `authored_by` are containment/provenance, not dependency.
IMPACT_PREDICATES: tuple[str, ...] = (
    "calls",
    "imports",
    "references",
    "depends_on",
    "handled_by",
    "extends",
    "implements",
    "decorated_by",
    "defined_in",
)


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
                properties TEXT,
                domain     TEXT NOT NULL DEFAULT 'code'
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_name
                ON nodes (name COLLATE NOCASE);

            CREATE TABLE IF NOT EXISTS edges (
                id          TEXT PRIMARY KEY,
                source_id   TEXT NOT NULL,
                target_id   TEXT NOT NULL,
                label       TEXT,
                properties  TEXT,
                source_file TEXT,
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
        # Idempotent migration: add domain column to existing DBs that lack it.
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(nodes)").fetchall()}
        if "domain" not in cols:
            self._conn.execute(
                "ALTER TABLE nodes ADD COLUMN domain TEXT NOT NULL DEFAULT 'code'"
            )
            self._conn.commit()
        # Always ensure the domain index exists (safe for new DBs too).
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_domain ON nodes (domain)"
        )
        self._conn.commit()
        ecols = {
            r[1] for r in self._conn.execute("PRAGMA table_info(edges)").fetchall()
        }
        if "source_file" not in ecols:
            self._conn.execute("ALTER TABLE edges ADD COLUMN source_file TEXT")
            self._conn.commit()
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_source_file ON edges (source_file)"
        )
        self._conn.commit()
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
                getattr(n, "domain", "code"),
            )
            for n in nodes
        ]
        self._conn.executemany(
            """
            INSERT INTO nodes (id, name, label, properties, domain)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                label = excluded.label,
                properties = CASE
                    WHEN excluded.properties IS NULL
                         OR excluded.properties IN ('{}', 'null', '')
                        THEN nodes.properties
                    ELSE excluded.properties
                END,
                domain = excluded.domain
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
            source_file = props.pop("source_file", None)
            eid = _edge_id(r.source_id, r.label, r.target_id)
            self._conn.execute(
                """
                INSERT INTO edges
                    (id, source_id, target_id, label, properties,
                     source_file, valid_from, valid_until)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    properties = excluded.properties,
                    source_file = excluded.source_file,
                    valid_from = excluded.valid_from,
                    valid_until = excluded.valid_until
                """,
                (
                    eid,
                    r.source_id,
                    r.target_id,
                    r.label,
                    json.dumps(props, default=str),
                    source_file,
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

    def invalidate_by_source_file(self, source_file: str, domain: str = "code") -> int:
        """Temporally close all currently-valid edges from this source file whose
        endpoints are nodes of the given domain. Returns the count invalidated."""
        now = _now_iso()
        cur = self._conn.execute(
            """
            UPDATE edges
               SET valid_until = ?
             WHERE source_file = ?
               AND valid_until IS NULL
               AND source_id IN (SELECT id FROM nodes WHERE domain = ?)
            """,
            (now, source_file, domain),
        )
        self._conn.commit()
        return cur.rowcount

    def sweep_orphan_nodes(self, domain: str = "code") -> int:
        """Delete nodes of `domain` that have no currently-valid edge (no edge
        with valid_until IS NULL touching them). Returns the count removed."""
        cur = self._conn.execute(
            """
            DELETE FROM nodes
             WHERE domain = ?
               AND id NOT IN (
                   SELECT source_id FROM edges WHERE valid_until IS NULL
                   UNION
                   SELECT target_id FROM edges WHERE valid_until IS NULL
               )
            """,
            (domain,),
        )
        self._conn.commit()
        return cur.rowcount

    def sweep_empty_folders(self, domain: str = "code") -> int:
        """Iteratively delete Folder nodes with no valid outgoing `contains`
        edge, invalidating chain edges that touched them. Folder→Folder chain
        edges carry no per-file provenance (shared across files), so this
        sweep — not the source-file purge — is what removes an emptied
        directory subtree. Returns the number of Folder nodes removed."""
        removed = 0
        now = _now_iso()
        while True:
            rows = self._conn.execute(
                """
                SELECT id FROM nodes
                 WHERE domain = ? AND label = 'Folder'
                   AND id NOT IN (
                       SELECT source_id FROM edges
                        WHERE label = 'contains' AND valid_until IS NULL
                   )
                """,
                (domain,),
            ).fetchall()
            ids = [r["id"] for r in rows]
            if not ids:
                break
            ph = ",".join("?" * len(ids))
            self._conn.execute(
                f"UPDATE edges SET valid_until = ? WHERE valid_until IS NULL "
                f"AND (source_id IN ({ph}) OR target_id IN ({ph}))",
                [now, *ids, *ids],
            )
            self._conn.execute(f"DELETE FROM nodes WHERE id IN ({ph})", ids)
            removed += len(ids)
        self._conn.commit()
        return removed

    def set_node_properties(self, props_by_id: dict[str, dict[str, Any]]) -> int:
        """Merge properties into EXISTING nodes; unknown ids are skipped.

        Merge (not replace) so independent writers (positions, future
        annotations) don't erase each other. Returns nodes updated."""
        updated = 0
        for node_id, props in props_by_id.items():
            row = self._conn.execute(
                "SELECT properties FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if row is None:
                continue
            merged = json.loads(row["properties"]) if row["properties"] else {}
            merged.update(props)
            self._conn.execute(
                "UPDATE nodes SET properties = ? WHERE id = ?",
                (json.dumps(merged, default=str), node_id),
            )
            updated += 1
        self._conn.commit()
        return updated

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """One node with parsed properties (detail panel / source endpoint)."""
        row = self._conn.execute(
            "SELECT id, name, label, domain, properties FROM nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "label": row["label"],
            "domain": row["domain"],
            "properties": json.loads(row["properties"]) if row["properties"] else {},
        }

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

    def nodes_by_label(
        self,
        label: str,
        contains: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Nodes of one label, optionally name-filtered (dashboard browse)."""
        sql = "SELECT id, name, label FROM nodes WHERE label = ?"
        params: list[Any] = [label]
        if contains:
            escaped = (
                contains.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            sql += " AND name LIKE ? ESCAPE '\\'"
            params.append(f"%{escaped}%")
        sql += " ORDER BY name LIMIT ?"
        params.append(max(0, limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [{"id": r["id"], "name": r["name"], "label": r["label"]} for r in rows]

    def timeline_named(self, entity_name: str) -> list[dict[str, Any]]:
        """Like ``timeline`` but with subject/object resolved to node names."""
        node_id = self._id_for_name(entity_name)
        if node_id is None:
            return []
        rows = self._conn.execute(
            "SELECT e.label AS predicate, e.valid_from, e.valid_until, "
            "       s.name AS subject, t.name AS object "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.source_id "
            "JOIN nodes t ON t.id = e.target_id "
            "WHERE e.source_id = ? OR e.target_id = ? "
            "ORDER BY e.valid_from, e.id",
            (node_id, node_id),
        ).fetchall()
        return [
            {
                "subject": r["subject"],
                "predicate": r["predicate"],
                "object": r["object"],
                "valid_from": r["valid_from"],
                "valid_until": r["valid_until"],
                "valid": r["valid_until"] is None,
            }
            for r in rows
        ]

    def search_nodes(
        self,
        text: str,
        limit: int = 20,
        domains: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Name-substring node search with active-edge degree (browser seeds)."""
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql = (
            "SELECT n.id, n.name, n.label, n.domain, "
            "  (SELECT count(*) FROM edges e "
            "   WHERE (e.source_id = n.id OR e.target_id = n.id) "
            "   AND e.valid_until IS NULL) AS degree "
            "FROM nodes n WHERE n.name LIKE ? ESCAPE '\\' COLLATE NOCASE "
        )
        params: list[Any] = [f"%{escaped}%"]
        if domains:
            ph = ",".join("?" * len(domains))
            sql += f"AND n.domain IN ({ph}) "
            params.extend(domains)
        sql += "ORDER BY degree DESC, n.name LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "label": r["label"],
                "domain": r["domain"],
                "degree": int(r["degree"]),
            }
            for r in rows
        ]

    def top_nodes(
        self,
        limit: int = 20,
        domains: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Highest active-edge-degree nodes — the graph's hubs. Backs the
        "start browser with no search" seed picker; only nodes with at least one
        active edge are returned (isolated nodes make a useless starting point)."""
        inner = (
            "SELECT n.id AS id, n.name AS name, n.label AS label, "
            "  n.domain AS domain, "
            "  (SELECT count(*) FROM edges e "
            "   WHERE (e.source_id = n.id OR e.target_id = n.id) "
            "   AND e.valid_until IS NULL) AS degree "
            "FROM nodes n"
        )
        params: list[Any] = []
        if domains:
            ph = ",".join("?" * len(domains))
            inner += f" WHERE n.domain IN ({ph})"
            params.extend(domains)
        rows = self._conn.execute(
            f"SELECT id, name, label, domain, degree FROM ({inner}) "
            "WHERE degree > 0 ORDER BY degree DESC, name LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "label": r["label"],
                "domain": r["domain"],
                "degree": int(r["degree"]),
            }
            for r in rows
        ]

    def neighbors(
        self,
        node_ids: list[str],
        limit: int = 200,
        domains: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Active edges touching ``node_ids`` plus every connected node. With
        ``domains``, an edge is returned only when BOTH endpoints' nodes are in
        an enabled domain (§3b — cross-domain edges render only when both
        endpoint domains are enabled)."""
        if not node_ids:
            return {"nodes": [], "edges": []}
        placeholders = ",".join("?" * len(node_ids))
        if domains:
            phd = ",".join("?" * len(domains))
            edge_rows = self._conn.execute(
                "SELECT e.id, e.source_id, e.target_id, e.label FROM edges e "
                "JOIN nodes s ON s.id = e.source_id "
                "JOIN nodes t ON t.id = e.target_id "
                f"WHERE (e.source_id IN ({placeholders}) "
                f"   OR e.target_id IN ({placeholders})) "
                "AND e.valid_until IS NULL "
                f"AND s.domain IN ({phd}) AND t.domain IN ({phd}) LIMIT ?",
                [*node_ids, *node_ids, *domains, *domains, limit],
            ).fetchall()
        else:
            edge_rows = self._conn.execute(
                "SELECT id, source_id, target_id, label FROM edges "
                f"WHERE (source_id IN ({placeholders}) "
                f"   OR target_id IN ({placeholders})) "
                "AND valid_until IS NULL LIMIT ?",
                [*node_ids, *node_ids, limit],
            ).fetchall()
        ids = set(node_ids)
        for r in edge_rows:
            ids.add(r["source_id"])
            ids.add(r["target_id"])
        node_rows: list[Any] = []
        id_list = list(ids)
        # Chunk the IN clause to stay under SQLite's bound-parameter limit.
        for i in range(0, len(id_list), 500):
            chunk = id_list[i : i + 500]
            ph = ",".join("?" * len(chunk))
            node_rows.extend(
                self._conn.execute(
                    "SELECT id, name, label, domain, properties, "
                    "(SELECT count(*) FROM edges e "
                    "  WHERE (e.source_id = nodes.id OR e.target_id = nodes.id) "
                    "    AND e.valid_until IS NULL) AS degree "
                    f"FROM nodes WHERE id IN ({ph})",
                    chunk,
                ).fetchall()
            )
        return {
            "nodes": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "label": r["label"],
                    "domain": r["domain"],
                    "degree": int(r["degree"]),
                    "properties": (
                        json.loads(r["properties"]) if r["properties"] else {}
                    ),
                }
                for r in node_rows
            ],
            "edges": [
                {
                    "id": r["id"],
                    "source": r["source_id"],
                    "target": r["target_id"],
                    "label": r["label"],
                }
                for r in edge_rows
            ],
        }

    def existing_node_ids(self, ids: list[str]) -> set[str]:
        """Subset of ``ids`` that exist as nodes (chunked IN — param limit)."""
        found: set[str] = set()
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            ph = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT id FROM nodes WHERE id IN ({ph})", chunk
            ).fetchall()
            found.update(r["id"] for r in rows)
        return found

    def nodes_by_exact_name(
        self,
        name: str,
        domains: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Exact case-sensitive display-name lookup (resolver tier 3).

        Distinct from ``search_nodes`` (substring, NOCASE, degree-ranked): the
        resolver needs the exact candidate set, never truncated by popularity.
        """
        sql = "SELECT id, name, label, domain FROM nodes WHERE name = ?"
        params: list[Any] = [name]
        if domains:
            ph = ",".join("?" * len(domains))
            sql += f" AND domain IN ({ph})"
            params.extend(domains)
        sql += " ORDER BY id LIMIT ?"
        params.append(max(1, limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "label": r["label"],
                "domain": r["domain"],
            }
            for r in rows
        ]

    def co_changed_files(
        self,
        file_id: str,
        min_shared: int = 2,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Files that share commits with ``file_id`` — the co-change view.

        Computed from currently-valid ``modifies`` edges (never materialised:
        pairs are O(files²) per commit). Weight = number of shared commits.
        Spec E decides whether this ever becomes stored edges / ranking input.
        """
        rows = self._conn.execute(
            """
            SELECT e2.target_id AS file_id,
                   n.name        AS name,
                   count(DISTINCT e2.source_id) AS shared_commits
              FROM edges e1
              JOIN edges e2
                ON e2.source_id = e1.source_id
               AND e2.label = 'modifies'
               AND e2.valid_until IS NULL
               AND e2.target_id != e1.target_id
              JOIN nodes n ON n.id = e2.target_id
             WHERE e1.label = 'modifies'
               AND e1.valid_until IS NULL
               AND e1.target_id = ?
             GROUP BY e2.target_id
            HAVING count(DISTINCT e2.source_id) >= ?
             ORDER BY shared_commits DESC, n.name
             LIMIT ?
            """,
            (file_id, max(1, min_shared), max(0, limit)),
        ).fetchall()
        return [
            {
                "file_id": r["file_id"],
                "name": r["name"],
                "shared_commits": int(r["shared_commits"]),
            }
            for r in rows
        ]

    def find_paths(
        self,
        src_id: str,
        dst_id: str,
        max_depth: int = 6,
        limit: int = 5,
        domains: list[str] | None = None,
    ) -> dict[str, Any]:
        """Shortest paths between two nodes over currently-valid edges.

        Undirected traversal (an edge can be walked either way) — each hop
        reports the edge's STORED direction. Level-synchronous BFS, so every
        returned path has minimal length; up to ``limit`` distinct paths.
        With ``domains``, an edge is walkable only when BOTH endpoints are in
        an enabled domain (same rule as :meth:`neighbors`).
        """
        empty: dict[str, Any] = {"paths": [], "nodes": []}
        if self.get_node(src_id) is None or self.get_node(dst_id) is None:
            return empty
        if src_id == dst_id:
            return {
                "paths": [{"node_ids": [src_id], "edges": [], "length": 0}],
                "nodes": self._nodes_meta([src_id]),
            }

        # parents[child] = list of (parent, edge_dict) recorded ONLY at the
        # BFS level where child is first discovered — multi-parent for
        # multiple equal-length paths.
        parents: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        visited: set[str] = {src_id}
        frontier: set[str] = {src_id}
        found = False
        for _depth in range(max_depth):
            if not frontier or len(visited) > _MAX_FRONTIER:
                break
            rows = self._edges_touching(frontier, domains)
            next_frontier: set[str] = set()
            for r in rows:
                for a, b in (
                    (r["source_id"], r["target_id"]),
                    (r["target_id"], r["source_id"]),
                ):
                    if a in frontier and b not in visited:
                        edge = {
                            "source": r["source_id"],
                            "target": r["target_id"],
                            "label": r["label"],
                        }
                        parents.setdefault(b, []).append((a, edge))
                        next_frontier.add(b)
            if dst_id in next_frontier:
                found = True
                break
            visited |= next_frontier
            frontier = next_frontier
        if not found:
            return empty

        # Reconstruct up to `limit` paths dst → src through the parent links.
        paths: list[dict[str, Any]] = []

        def _walk(node: str, node_ids: list[str], edges: list[dict[str, Any]]) -> None:
            if len(paths) >= max(1, limit):
                return
            if node == src_id:
                ids = [src_id, *reversed(node_ids)]
                paths.append(
                    {
                        "node_ids": ids,
                        "edges": list(reversed(edges)),
                        "length": len(edges),
                    }
                )
                return
            for parent, edge in parents.get(node, []):
                _walk(parent, [*node_ids, node], [*edges, edge])

        _walk(dst_id, [], [])
        seen_ids: set[str] = set()
        for p in paths:
            seen_ids.update(p["node_ids"])
        return {"paths": paths, "nodes": self._nodes_meta(sorted(seen_ids))}

    def impact(
        self,
        node_id: str,
        max_depth: int = 3,
        predicates: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Nodes that transitively depend on ``node_id`` (reverse closure).

        Walks currently-valid edges BACKWARDS (target → source) over the
        dependency ``predicates`` (default :data:`IMPACT_PREDICATES`). Each
        dependent is reported once, at its shallowest depth, BFS order.
        """
        if self.get_node(node_id) is None:
            return []
        preds = list(predicates) if predicates else list(IMPACT_PREDICATES)
        php = ",".join("?" * len(preds))
        visited: set[str] = {node_id}
        frontier: list[str] = [node_id]
        hits: list[dict[str, Any]] = []
        for depth in range(1, max_depth + 1):
            if not frontier or len(hits) >= limit:
                break
            next_frontier: list[str] = []
            for i in range(0, len(frontier), 400):
                chunk = frontier[i : i + 400]
                ph = ",".join("?" * len(chunk))
                rows = self._conn.execute(
                    "SELECT source_id, target_id, label FROM edges "
                    f"WHERE target_id IN ({ph}) AND label IN ({php}) "
                    "AND valid_until IS NULL",
                    [*chunk, *preds],
                ).fetchall()
                for r in rows:
                    dep = r["source_id"]
                    if dep in visited:
                        continue
                    visited.add(dep)
                    next_frontier.append(dep)
                    hits.append(
                        {
                            "id": dep,
                            "depth": depth,
                            "via_predicate": r["label"],
                            "via_node_id": r["target_id"],
                        }
                    )
            frontier = next_frontier
        hits = hits[: max(0, limit)]
        meta = {m["id"]: m for m in self._nodes_meta([h["id"] for h in hits])}
        return [
            {
                "id": h["id"],
                "name": meta.get(h["id"], {}).get("name", h["id"]),
                "label": meta.get(h["id"], {}).get("label"),
                "domain": meta.get(h["id"], {}).get("domain"),
                "depth": h["depth"],
                "via_predicate": h["via_predicate"],
                "via_node_id": h["via_node_id"],
            }
            for h in hits
        ]

    def _edges_touching(
        self, node_ids: set[str], domains: list[str] | None
    ) -> list[sqlite3.Row]:
        """Active edges with either endpoint in ``node_ids`` (chunked IN)."""
        out: list[sqlite3.Row] = []
        ids = sorted(node_ids)
        for i in range(0, len(ids), 400):
            chunk = ids[i : i + 400]
            ph = ",".join("?" * len(chunk))
            if domains:
                phd = ",".join("?" * len(domains))
                out.extend(
                    self._conn.execute(
                        "SELECT e.source_id, e.target_id, e.label FROM edges e "
                        "JOIN nodes s ON s.id = e.source_id "
                        "JOIN nodes t ON t.id = e.target_id "
                        f"WHERE (e.source_id IN ({ph}) OR e.target_id IN ({ph})) "
                        "AND e.valid_until IS NULL "
                        f"AND s.domain IN ({phd}) AND t.domain IN ({phd})",
                        [*chunk, *chunk, *domains, *domains],
                    ).fetchall()
                )
            else:
                out.extend(
                    self._conn.execute(
                        "SELECT source_id, target_id, label FROM edges "
                        f"WHERE (source_id IN ({ph}) OR target_id IN ({ph})) "
                        "AND valid_until IS NULL",
                        [*chunk, *chunk],
                    ).fetchall()
                )
        return out

    def _nodes_meta(self, ids: list[str]) -> list[dict[str, Any]]:
        """id/name/label/domain rows for ``ids`` (chunked IN)."""
        out: list[dict[str, Any]] = []
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            ph = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT id, name, label, domain FROM nodes WHERE id IN ({ph})",
                chunk,
            ).fetchall()
            out.extend(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "label": r["label"],
                    "domain": r["domain"],
                }
                for r in rows
            )
        return out

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
