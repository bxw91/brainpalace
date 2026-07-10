"""Identity store (G5 / spec ``.planning/specs/2026-07-09-g5-identity-store.md``):
the engine's first-class home for *who someone is* — ``person`` / ``alias`` /
``link`` — as user-asserted ground truth.

Own SQLite file (D1): identity is asserted truth and must never live in a
rebuildable cache like the graph store. Conventions mirror
``reference_catalog_store.py`` verbatim — standalone
``sqlite3.connect(check_same_thread=False)``, ``PRAGMA journal_mode=WAL``,
``PRAGMA busy_timeout=5000``, ``_init_schema`` via ``executescript``, pydantic
row models, ``with self._conn:`` transactions.

Scope of THIS module (Task 4): store + deterministic candidate lookup only. It
does NOT resolve a ``link.ref`` to a live ``chunk_id`` (that is retrieval,
Task 8), it is NOT wired into the API (Task 7), and it never picks a winner —
``resolve_candidates`` returns a ranked list and the *app* decides (D7).

Design points held from the spec:
  * ``person.name`` is NULLable — an unnamed row IS the "unknown person" (D3);
    ``name_person`` promotes it in place, same id.
  * ``link.person_id`` is NULLable — unresolved is a legal terminal state (D7),
    with its candidate set carried in the ``candidates`` JSON column.
  * ``alias`` is scoped (``scope`` = speaker's person id, NULL = global) and
    time-bounded (``valid_from`` / ``valid_to``); resolution is evaluated at the
    *mention's* timestamp ``at``, never ``now()`` (D4).
  * ``person.sensitivity`` (A5) ships now so no migration is needed later; it
    mirrors the chunk/record ``"normal"``-default vocabulary (non-``normal`` =
    hidden from default queries).

Columns beyond the spec's illustrative DDL, added because a listed method is
otherwise inert (same rationale by which the coordinator front-loads
``person.sensitivity``): ``link.stale`` (backs ``stale_mark`` / Task 6's
re-ingest cascade), and ``link.surface`` / ``link.scope`` (an unresolved link
must remember what surface+scope it is trying to resolve so ``backfill`` can
re-score it against newly-added aliases — the spec's ``ref`` is a chunk/session
address, not the surface string).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# A link addresses `source_id` when its ref is the bare source_id (participant)
# or the chunk address `{source_id}#{chunk_index}` (speaker / mentioned).
#
# Deliberately NOT `ref LIKE source_id || '#%'`: `_` and `%` are LIKE wildcards,
# and source_ids routinely contain underscores (`msg_2026_07_09`), so LIKE would
# match — and DELETE — a different source's links. Compare the prefix exactly.
_ADDRESSES_SOURCE = "(ref = ? OR substr(ref, 1, ?) = ?)"


def _addresses_source_params(source_id: str) -> tuple[str, int, str]:
    prefix = source_id + "#"
    return (source_id, len(prefix), prefix)


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = ""  # generated on insert when empty
    name: str | None = None  # NULL = unknown person (D3)
    kind: str
    domain: str
    sensitivity: str = "normal"
    created_at: str | None = None  # stamped on insert when None


class Alias(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surface: str
    person_id: str
    scope: str | None = None  # speaker person id; NULL = global (D4)
    valid_from: str | None = None
    valid_to: str | None = None


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = ""  # generated on insert when empty
    ref: str  # chunk address "{source_id}#{idx}" | session_id | opaque key (A1)
    ref_kind: str  # chunk | span | session | external
    role: str  # speaker | mentioned | participant (D5)
    method: str  # user_asserted | call_log | llm_inferred | alias_match (D6)
    at: str  # mention time, drives D4 resolution
    person_id: str | None = None  # NULL = unresolved (D7)
    span_start: int | None = None
    span_end: int | None = None
    candidates: list[dict[str, Any]] | None = None  # [{person_id,score,evidence}]
    confidence: float | None = None
    surface: str | None = None  # surface this link resolves (for backfill)
    scope: str | None = None  # scope for backfill re-scoring
    stale: int = 0
    created_at: str | None = None


_LINK_COLS = (
    "id,ref,ref_kind,span_start,span_end,role,person_id,candidates,"
    "method,confidence,at,surface,scope,stale,created_at"
)


class IdentityStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS person (
                id TEXT PRIMARY KEY,
                name TEXT,
                kind TEXT NOT NULL,
                domain TEXT NOT NULL,
                sensitivity TEXT NOT NULL DEFAULT 'normal',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alias (
                surface TEXT NOT NULL,
                scope TEXT,
                person_id TEXT NOT NULL REFERENCES person(id),
                valid_from TEXT,
                valid_to TEXT,
                PRIMARY KEY (surface, scope, person_id, valid_from)
            );
            CREATE TABLE IF NOT EXISTS link (
                id TEXT PRIMARY KEY,
                ref TEXT NOT NULL,
                ref_kind TEXT NOT NULL,
                span_start INTEGER,
                span_end INTEGER,
                role TEXT NOT NULL,
                person_id TEXT REFERENCES person(id),
                candidates TEXT,
                method TEXT NOT NULL,
                confidence REAL,
                at TEXT NOT NULL,
                surface TEXT,
                scope TEXT,
                stale INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_link_person_role ON link(person_id, role);
            CREATE INDEX IF NOT EXISTS idx_link_ref ON link(ref);
            CREATE INDEX IF NOT EXISTS idx_alias_surface_scope ON alias(surface, scope);
            CREATE INDEX IF NOT EXISTS idx_link_unresolved
                ON link(person_id) WHERE person_id IS NULL;
            """
        )
        self._conn.commit()

    # --- person ---------------------------------------------------------

    def upsert_person(self, person: Person) -> str:
        pid = person.id or _uuid()
        created = person.created_at or _now()
        with self._conn:
            self._conn.execute(
                """INSERT INTO person (id,name,kind,domain,sensitivity,created_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name, kind=excluded.kind,
                     domain=excluded.domain, sensitivity=excluded.sensitivity""",
                (
                    pid,
                    person.name,
                    person.kind,
                    person.domain,
                    person.sensitivity,
                    created,
                ),
            )
        return pid

    def name_person(self, person_id: str, name: str) -> bool:
        """Promote an unknown (name IS NULL) person in place (D3) — same id."""
        with self._conn:
            cur = self._conn.execute(
                "UPDATE person SET name=? WHERE id=?", (name, person_id)
            )
        return cur.rowcount > 0

    def get_person(self, person_id: str) -> Person | None:
        row = self._conn.execute(
            "SELECT id,name,kind,domain,sensitivity,created_at "
            "FROM person WHERE id=?",
            (person_id,),
        ).fetchone()
        if row is None:
            return None
        return Person(
            id=row[0],
            name=row[1],
            kind=row[2],
            domain=row[3],
            sensitivity=row[4],
            created_at=row[5],
        )

    # --- alias ----------------------------------------------------------

    def upsert_alias(self, alias: Alias) -> None:
        # NULL-safe idempotency: a global (scope NULL) or open-ended
        # (valid_from NULL) alias would slip past ON CONFLICT because SQLite
        # treats NULL PK components as distinct — so delete-by-IS then insert.
        with self._conn:
            self._conn.execute(
                "DELETE FROM alias WHERE surface=? AND scope IS ? "
                "AND person_id=? AND valid_from IS ?",
                (alias.surface, alias.scope, alias.person_id, alias.valid_from),
            )
            self._conn.execute(
                "INSERT INTO alias (surface,scope,person_id,valid_from,valid_to) "
                "VALUES (?,?,?,?,?)",
                (
                    alias.surface,
                    alias.scope,
                    alias.person_id,
                    alias.valid_from,
                    alias.valid_to,
                ),
            )

    # --- link -----------------------------------------------------------

    def add_link(self, link: Link) -> str:
        lid = link.id or _uuid()
        created = link.created_at or _now()
        cands = json.dumps(link.candidates) if link.candidates is not None else None
        with self._conn:
            self._conn.execute(
                f"INSERT INTO link ({_LINK_COLS}) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    lid,
                    link.ref,
                    link.ref_kind,
                    link.span_start,
                    link.span_end,
                    link.role,
                    link.person_id,
                    cands,
                    link.method,
                    link.confidence,
                    link.at,
                    link.surface,
                    link.scope,
                    link.stale,
                    created,
                ),
            )
        return lid

    def retract_link(self, link_id: str) -> bool:
        """Delete a link (D6). Never touches the person or alias rows."""
        with self._conn:
            cur = self._conn.execute("DELETE FROM link WHERE id=?", (link_id,))
        return cur.rowcount > 0

    @staticmethod
    def _link_from_row(row: tuple[Any, ...]) -> Link:
        return Link(
            id=row[0],
            ref=row[1],
            ref_kind=row[2],
            span_start=row[3],
            span_end=row[4],
            role=row[5],
            person_id=row[6],
            candidates=json.loads(row[7]) if row[7] else None,
            method=row[8],
            confidence=row[9],
            at=row[10],
            surface=row[11],
            scope=row[12],
            stale=row[13],
            created_at=row[14],
        )

    def links_for_person(self, person_id: str, role: str | None = None) -> list[Link]:
        sql = f"SELECT {_LINK_COLS} FROM link WHERE person_id=?"
        params: list[Any] = [person_id]
        if role is not None:
            sql += " AND role=?"
            params.append(role)
        return [self._link_from_row(r) for r in self._conn.execute(sql, tuple(params))]

    def persons_for_ref(
        self, ref: str, *, include_sensitive: bool = False
    ) -> list[str]:
        """Resolved person ids linked to ``ref`` (chunk address or bare
        source_id), for retrieval-side grouping (G5 Task 8). A5: non-``normal``
        persons are excluded unless ``include_sensitive`` — the caller passes
        the same include-sensitive switch used for chunk-level default-deny."""
        sql = (
            "SELECT DISTINCT l.person_id FROM link l "
            "JOIN person p ON p.id = l.person_id "
            "WHERE l.ref = ? AND l.person_id IS NOT NULL"
        )
        if not include_sensitive:
            sql += " AND p.sensitivity = 'normal'"
        return [row[0] for row in self._conn.execute(sql, (ref,))]

    def unresolved(self) -> list[Link]:
        return [
            self._link_from_row(r)
            for r in self._conn.execute(
                f"SELECT {_LINK_COLS} FROM link WHERE person_id IS NULL"
            )
        ]

    # --- resolution -----------------------------------------------------

    def resolve_candidates(
        self,
        surface: str,
        scope: str | None = None,
        at: str | None = None,
        *,
        ref: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Ranked ``[{person_id, score, evidence}]`` — deterministic, no LLM,
        no network. NEVER picks a winner; ties are returned as ties and the
        margin/threshold decision lives in the consumer app.

        Scoring tiers (spec ``## Scoring``), evidence carried alongside:
          1. exact alias match in ``scope``, valid at ``at``
          2. exact alias match, global scope (only when a scope was given)
          3. co-occurrence: other resolved persons on the same ``ref``
          4. recency: resolved persons elsewhere in the same session
        Graph proximity (tier 5) is Task 9 and deliberately omitted here.
        """
        at = at or _now()
        scores: dict[str, float] = {}
        evidence: dict[str, list[str]] = defaultdict(list)

        def _bump(pid: str, amount: float, tag: str) -> None:
            scores[pid] = scores.get(pid, 0.0) + amount
            evidence[pid].append(tag)

        valid = (
            "(valid_from IS NULL OR valid_from <= ?) "
            "AND (valid_to IS NULL OR ? < valid_to)"
        )

        # Tier 1: alias in the requested scope (scope IS ? matches NULL global
        # when scope itself is None — a global-only resolution).
        for (pid,) in self._conn.execute(
            f"SELECT person_id FROM alias WHERE surface=? AND scope IS ? AND {valid}",
            (surface, scope, at, at),
        ):
            _bump(pid, 4.0, "alias:scope")

        # Tier 2: global aliases, only added when a non-global scope was asked
        # for (otherwise tier 1 already covered the global rows).
        if scope is not None:
            for (pid,) in self._conn.execute(
                f"SELECT person_id FROM alias "
                f"WHERE surface=? AND scope IS NULL AND {valid}",
                (surface, at, at),
            ):
                _bump(pid, 3.0, "alias:global")

        # Tier 3: co-occurrence — resolved persons already on this ref.
        if ref:
            for (pid,) in self._conn.execute(
                "SELECT DISTINCT person_id FROM link "
                "WHERE ref=? AND person_id IS NOT NULL",
                (ref,),
            ):
                _bump(pid, 2.0, f"cooccurrence:{ref}")

        # Tier 4: recency — resolved persons elsewhere in the same session.
        if session_id:
            for (pid,) in self._conn.execute(
                "SELECT DISTINCT person_id FROM link "
                f"WHERE person_id IS NOT NULL AND {_ADDRESSES_SOURCE}",
                _addresses_source_params(session_id),
            ):
                _bump(pid, 1.0, f"recency:{session_id}")

        ranked = sorted(scores, key=lambda pid: scores[pid], reverse=True)
        return [
            {"person_id": pid, "score": scores[pid], "evidence": evidence[pid]}
            for pid in ranked
        ]

    def backfill(self) -> int:
        """Re-score every unresolved link against the current aliases and
        refresh its stored candidate set. Never resolves a link (the engine
        does not guess — D7); only the candidate list is updated."""
        n = 0
        for link in self.unresolved():
            if not link.surface:
                continue
            session_id = link.ref.split("#", 1)[0] if link.ref else None
            cands = self.resolve_candidates(
                link.surface,
                link.scope,
                link.at,
                ref=link.ref,
                session_id=session_id,
            )
            with self._conn:
                self._conn.execute(
                    "UPDATE link SET candidates=? WHERE id=?",
                    (json.dumps(cands), link.id),
                )
            n += 1
        return n

    # --- cascade / lifecycle -------------------------------------------

    def stale_mark(self, source_id: str, alive_refs: set[str] | None = None) -> int:
        """Mark ``role=mentioned`` links for ``source_id`` stale (never delete
        — staleness is surfaced, not swallowed; spec A1).

        ``alive_refs=None`` (default) marks every ``role='mentioned'`` link
        addressing ``source_id`` — the original Task 4 behavior. When a set is
        passed (Task 6's re-ingest cascade), only links whose ``ref`` is NOT in
        ``alive_refs`` are marked, narrowing staleness to the chunk positions
        whose text actually changed."""
        with self._conn:
            if alive_refs is None:
                cur = self._conn.execute(
                    "UPDATE link SET stale=1 WHERE role='mentioned' "
                    f"AND {_ADDRESSES_SOURCE}",
                    _addresses_source_params(source_id),
                )
            elif not alive_refs:
                # No alive refs at all: every mentioned link for this source
                # addresses a position that no longer exists — mark them all.
                cur = self._conn.execute(
                    "UPDATE link SET stale=1 WHERE role='mentioned' "
                    f"AND {_ADDRESSES_SOURCE}",
                    _addresses_source_params(source_id),
                )
            else:
                placeholders = ",".join("?" for _ in alive_refs)
                params = _addresses_source_params(source_id) + tuple(alive_refs)
                cur = self._conn.execute(
                    "UPDATE link SET stale=1 WHERE role='mentioned' "
                    f"AND {_ADDRESSES_SOURCE} "
                    f"AND ref NOT IN ({placeholders})",
                    params,
                )
        return cur.rowcount

    def delete_by_source(self, source_id: str) -> int:
        """Drop links addressing ``source_id`` (participant refs the bare
        source_id, speaker/mentioned ref ``{source_id}#{idx}``). External-key
        links (``ref_kind='external'``) are never source-addressed — a voice
        cluster / phone number that happens to equal ``source_id`` is left
        alone. Persons and aliases are user-asserted ground truth and are NOT
        deleted."""
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM link WHERE ref_kind != 'external' "
                f"AND {_ADDRESSES_SOURCE}",
                _addresses_source_params(source_id),
            )
        return cur.rowcount

    def count(self) -> int:
        """Number of persons (the store's primary entity; the dashboard
        surfaces this + the unresolved-link count)."""
        return int(self._conn.execute("SELECT COUNT(*) FROM person").fetchone()[0])
