"""Recover lost vector chunks from dead Chroma segments + the embedding cache.

A collection recreation (``heal_if_corrupt`` rebuild, a ``reset``, a
duplicate-server stomp) drops the old segment's ``segments`` row but leaves its
``embeddings`` / ``embedding_metadata`` rows behind in ``chroma.sqlite3``. Those
rows are **invisible to the collection API** (they belong to no live segment),
so every API-level reconcile/cleanup is blind to them — yet they still hold the
chunk **text + metadata**. The HNSW vectors are gone (the segment dir was
pruned), but the **embedding cache** still holds each vector keyed by
``SHA256(text)``.

This module restores the manifest's *missing* chunks into the live collection
from those two survivors:

  missing chunk  ──text+metadata──▶  dead segment row (chroma.sqlite3)
                 ──vector──────────▶  embedding cache (embeddings.db)
                 ──upsert──────────▶  live collection (writes through HNSW)

**No re-embed, no external provider call.** The restored vector is the cached
vector verbatim. Chunks whose text is gone (no dead row) or whose vector was
evicted from the cache are reported as unrecoverable, never re-embedded here.

The caller uses :attr:`RecoverySummary.complete` as a gate: a destructive
``deep_clean`` must NOT run unless recovery fully succeeded (no error, every
*possible* chunk restored).
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brainpalace_server.storage_paths import STATE_SUBDIR

logger = logging.getLogger(__name__)

_DOCUMENT_KEY = "chroma:document"


@dataclass
class RecoveredChunk:
    """A chunk reconstructed from a dead segment: its text + metadata."""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoverySummary:
    """Outcome of a lost-chunk recovery sweep.

    ``wanted`` = manifest chunks missing from the live store.
    ``recoverable`` = of those, the ones with BOTH dead-segment text and a cache
    vector (i.e. restorable without re-embedding). ``restored`` = actually
    written. ``missed`` = recoverable but the write failed. ``no_text`` /
    ``no_vector`` = the genuinely-unrecoverable residue (need a source re-index).
    """

    wanted: int = 0
    recoverable: int = 0
    restored: int = 0
    missed: int = 0
    no_text: int = 0
    no_vector: int = 0
    dry_run: bool = False
    error: str | None = None

    @property
    def complete(self) -> bool:
        """True only when recovery fully succeeded — the deep_clean gate.

        Destructive cleanup may proceed only if (a) no error, (b) this was a real
        run (a dry-run never opens the gate), and (c) every *possible* chunk (text
        + cache vector present) was restored. The unrecoverable residue
        (``no_text`` / ``no_vector``) does not block: it was never restorable
        here, only a source re-index can bring it back.
        """
        return (
            self.error is None
            and not self.dry_run
            and self.missed == 0
            and self.restored == self.recoverable
        )


def _batched(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _typed(sv: Any, iv: Any, fv: Any, bv: Any) -> Any:
    """Pick the one populated typed column from a Chroma metadata row."""
    if sv is not None:
        return sv
    if iv is not None:
        return iv
    if fv is not None:
        return fv
    if bv is not None:
        return bool(bv)
    return None


def read_recoverable_chunks(
    chroma_sqlite_path: str | Path, wanted_ids: Iterable[str]
) -> dict[str, RecoveredChunk]:
    """Return ``{chunk_id: RecoveredChunk}`` for wanted ids found in DEAD segments.

    A chunk is read only from a *dead* segment (one absent from the ``segments``
    table). Any wanted id that still has a row in a *live* segment is skipped —
    it isn't lost. The document text is split out of the metadata. Read-only;
    never raises (a backend error yields whatever was gathered).
    """
    wanted = set(wanted_ids)
    if not wanted:
        return {}
    path = Path(chroma_sqlite_path)
    if not path.exists():
        return {}

    out: dict[str, RecoveredChunk] = {}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        live_segments = {r[0] for r in con.execute("SELECT id FROM segments")}
        alive_ids: set[str] = set()
        # chunk_id is position-based (md5(source_idx)), not content-based, so one
        # id can have several historical texts across stranded generations. Keep
        # the LATEST dead occurrence (highest embeddings.id = most recently
        # indexed) so we restore the freshest content, matching the manifest.
        latest_rowid: dict[str, int] = {}

        for batch in _batched(sorted(wanted), 500):
            placeholders = ",".join("?" * len(batch))
            rows = con.execute(
                f"SELECT id, embedding_id, segment_id FROM embeddings "
                f"WHERE embedding_id IN ({placeholders})",
                batch,
            ).fetchall()
            for emb_rowid, eid, seg in rows:
                if seg in live_segments:
                    alive_ids.add(eid)
                elif emb_rowid > latest_rowid.get(eid, -1):
                    latest_rowid[eid] = emb_rowid

        for eid, emb_rowid in latest_rowid.items():
            if eid in alive_ids:
                continue  # still alive in the collection — not lost
            meta_rows = con.execute(
                "SELECT key, string_value, int_value, float_value, bool_value "
                "FROM embedding_metadata WHERE id=?",
                (emb_rowid,),
            ).fetchall()
            text = ""
            metadata: dict[str, Any] = {}
            for key, sv, iv, fv, bv in meta_rows:
                if key == _DOCUMENT_KEY:
                    text = sv or ""
                    continue
                metadata[key] = _typed(sv, iv, fv, bv)
            out[eid] = RecoveredChunk(text=text, metadata=metadata)
    except Exception as exc:  # noqa: BLE001 — read probe must never crash recovery
        logger.warning("read_recoverable_chunks failed for %s: %s", path, exc)
    finally:
        con.close()
    return out


def load_cache_vectors(
    cache_db_path: str | Path | None,
    content_hashes: Iterable[str],
    target_dimensions: int,
) -> dict[str, list[float]]:
    """Return ``{content_hash: vector}`` for the wanted SHA-256 text hashes.

    The cache key is ``SHA256(text):provider:model:dimensions``; this matches by
    the hash prefix (casing-independent of provider/model) and keeps only entries
    whose ``dimensions`` equal ``target_dimensions`` — a vector of the wrong
    width can't go into the live collection. Read-only; never raises.
    """
    hashes = set(content_hashes)
    out: dict[str, list[float]] = {}
    if not hashes or cache_db_path is None:
        return out
    path = Path(cache_db_path)
    if not path.exists():
        return out

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        # First pass: map wanted hash -> a dims-matched cache_key (cheap; keys
        # only). Then fetch just the matched blobs.
        matched: dict[str, str] = {}
        for cache_key, dims in con.execute(
            "SELECT cache_key, dimensions FROM embeddings"
        ):
            content_hash = cache_key.split(":", 1)[0]
            if (
                content_hash in hashes
                and dims == target_dimensions
                and content_hash not in matched
            ):
                matched[content_hash] = cache_key

        for content_hash, cache_key in matched.items():
            row = con.execute(
                "SELECT embedding, dimensions FROM embeddings WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
            if row is None:
                continue
            blob, dims = row
            if dims != target_dimensions:
                continue
            out[content_hash] = list(struct.unpack(f"{dims}f", blob))
    except Exception as exc:  # noqa: BLE001 — cache probe must never crash recovery
        logger.warning("load_cache_vectors failed for %s: %s", path, exc)
    finally:
        con.close()
    return out


def detect_dimensions(
    *, cache_db_path: str | Path | None = None, vector_store: Any = None
) -> int | None:
    """Best-effort embedding dimension for recovery (never raises).

    Prefers the cache ``provider_fingerprint`` (``provider:model:dims``) — the
    authoritative width of the cached vectors we restore from — then falls back
    to sampling one live vector. Returns ``None`` when neither is available.
    """
    if cache_db_path is not None:
        path = Path(cache_db_path)
        if path.exists():
            try:
                con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                try:
                    row = con.execute(
                        "SELECT value FROM metadata WHERE key='provider_fingerprint'"
                    ).fetchone()
                finally:
                    con.close()
                if row and row[0]:
                    tail = str(row[0]).rsplit(":", 1)[-1]
                    if tail.isdigit():
                        return int(tail)
            except Exception:  # noqa: BLE001 — probe must never crash startup
                pass

    coll = getattr(vector_store, "_collection", None)
    if coll is not None:
        try:
            res = coll.get(limit=1, include=["embeddings"])
            embs = res.get("embeddings")
            if embs is not None and len(embs) > 0:
                return len(embs[0])
        except Exception:  # noqa: BLE001 — probe must never crash startup
            pass
    return None


def _recovery_events_path(persist_dir: str | Path) -> Path | None:
    """``<state_dir>/recovery-events.jsonl`` (mirrors heal_events_path layout)."""
    persist = Path(persist_dir)
    if persist.parent.name != "data":
        return None  # legacy/non-standard layout — skip the marker
    # Pure path compute (no mkdir) — writers create the dir before appending.
    return persist.parent.parent / STATE_SUBDIR / "recovery-events.jsonl"


def _wanted_fingerprint(wanted: set[str]) -> str:
    """Order-independent fingerprint of the wanted-id set, so the presence
    fast-path can tell "same wanted set as last verified" from "it grew/shrank"
    (a new commit or a new file changes this; orphan churn in the store does not).
    """
    h = hashlib.sha256()
    for cid in sorted(wanted):
        h.update(cid.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def load_presence_state(path: str | Path | None) -> dict[str, Any] | None:
    """Read the recovery presence baseline (``{wanted_fp, store_count}``) written
    after a run that verified every wanted id present, or None if absent/corrupt."""
    if path is None:
        return None
    import json

    try:
        p = Path(path)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 — a missing/corrupt baseline just forces a probe
        return None


def save_presence_state(
    path: str | Path | None, wanted_fp: str, store_count: int
) -> None:
    """Persist the presence baseline so the next start can skip the per-id probe
    when the wanted set is unchanged and the store hasn't shrunk. Never raises."""
    if path is None:
        return
    import json

    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"wanted_fp": wanted_fp, "store_count": store_count}),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 — caching must never block startup
        logger.warning("save_presence_state failed: %s", exc)


def record_recovery_event(persist_dir: str | Path, event: dict[str, Any]) -> None:
    """Append one self-heal recovery event to ``recovery-events.jsonl`` (audit).

    Surfaced by ``brainpalace status`` so a recovery (or a blocked/incomplete
    one) is visible after the fact, not just a scrolled-past startup log. Never
    raises.
    """
    path = _recovery_events_path(persist_dir)
    if path is None:
        return
    import json
    from datetime import datetime, timezone

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as exc:  # noqa: BLE001 — auditing must never block startup
        logger.warning("record_recovery_event failed: %s", exc)


def read_recovery_events(persist_dir: str | Path, limit: int = 20) -> dict[str, Any]:
    """Read the recovery-event log for status reporting (best-effort, never raises)."""
    path = _recovery_events_path(persist_dir)
    if path is None or not path.exists():
        return {"count": 0, "last": None}
    import json

    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:  # noqa: BLE001 — skip a corrupt line
                continue
    except Exception as exc:  # noqa: BLE001 — never fail status on the log
        logger.warning("read_recovery_events failed: %s", exc)
        return {"count": 0, "last": None}
    return {
        "count": len(events),
        "last": events[-1] if events else None,
        "recent": events[-limit:],
    }


def rebuild_bm25_from_collection(bm25_manager: Any, vector_store: Any) -> int:
    """Rebuild the BM25 lexical index from every live-collection chunk.

    BM25 is a full-rebuild index keyed by chunk id and is **purely lexical — no
    embeddings, no provider calls**. After recovery upserts restored chunks into
    the vector store, this re-tokenizes the WHOLE live collection so keyword and
    hybrid(bm25) search find the restored chunks too. Returns the node count
    (0 when not applicable). Never raises.
    """
    if bm25_manager is None or vector_store is None:
        return 0
    coll = getattr(vector_store, "_collection", None)
    if coll is None:
        return 0
    try:
        from llama_index.core.schema import TextNode

        data = coll.get(include=["documents", "metadatas"])
        ids = data.get("ids") or []
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        nodes = []
        for i, cid in enumerate(ids):
            meta = dict(metas[i] if i < len(metas) and metas[i] else {})
            # BM25 indexes only code/doc chunks — git_commit / session_turn live
            # in the same collection but were never part of the lexical index.
            if meta.get("source_type") not in ("code", "doc"):
                continue
            nodes.append(
                TextNode(
                    id_=cid,
                    text=(docs[i] if i < len(docs) and docs[i] else ""),
                    metadata=meta,
                )
            )
        if not nodes:
            return 0
        bm25_manager.build_index(nodes)
        logger.warning(
            "chunk-recovery: rebuilt BM25 lexical index over %d chunk(s) so "
            "keyword search finds restored chunks (no re-embed).",
            len(nodes),
        )
        return len(nodes)
    except Exception as exc:  # noqa: BLE001 — BM25 rebuild must never crash startup
        logger.warning("rebuild_bm25_from_collection failed: %s", exc)
        return 0


async def recover_lost_chunks(
    *,
    vector_store: Any,
    wanted_ids: Iterable[str],
    chroma_sqlite_path: str | Path,
    cache_db_path: str | Path | None,
    target_dimensions: int,
    dry_run: bool = False,
    presence_state_path: str | Path | None = None,
) -> RecoverySummary:
    """Restore wanted chunks the live store has lost, from dead segments + cache.

    ``wanted_ids`` is the set the index *should* contain — the union of every
    folder manifest's chunk ids plus (optionally) the current git_commit ids.
    No external embedding is ever performed: the restored vector is the cached
    vector verbatim. Returns a :class:`RecoverySummary`; on any unexpected error
    it sets ``error`` and returns (so the caller's gate stays closed) rather than
    raising.
    """
    summary = RecoverySummary(dry_run=dry_run)
    try:
        wanted = set(wanted_ids)
        if not wanted:
            return summary

        try:
            store_count = await vector_store.get_count()
        except Exception:  # noqa: BLE001 — count probe must never crash heal
            store_count = None

        # Fast pre-check (orphan-tolerant). The store legitimately holds MORE than
        # `wanted` — e.g. orphan git_commit chunks for commits reachable only on
        # other branches / before a history rewrite, kept by the `rev-list --all`
        # deep-clean keep-set — so the old `store_count == len(wanted)` could never
        # pass and the per-id probe ran every start. Instead, skip the probe when
        # the wanted set is UNCHANGED since we last verified every id present AND
        # the store has not shrunk below that point. A real loss always lowers the
        # count, so this never skips an actual loss; new commits/files change the
        # fingerprint and force a re-probe; orphan churn only raises the count (or
        # at worst triggers a harmless extra probe).
        wanted_fp = _wanted_fingerprint(wanted)
        baseline = load_presence_state(presence_state_path)
        if (
            store_count is not None
            and baseline is not None
            and baseline.get("wanted_fp") == wanted_fp
            and store_count >= int(baseline.get("store_count", -1))
        ):
            return summary

        present = await vector_store.get_existing_ids(list(wanted))
        missing = wanted - set(present)
        summary.wanted = len(missing)
        if not missing:
            # All wanted ids present — record the baseline so the next start can
            # take the fast-path above (until wanted changes or the store shrinks).
            if store_count is not None:
                save_presence_state(presence_state_path, wanted_fp, store_count)
            return summary

        recovered = read_recoverable_chunks(chroma_sqlite_path, missing)
        summary.no_text = len(missing - recovered.keys())

        hashes = {
            hashlib.sha256(rc.text.encode("utf-8")).hexdigest()
            for rc in recovered.values()
        }
        vectors = load_cache_vectors(cache_db_path, hashes, target_dimensions)

        restorable: list[tuple[str, RecoveredChunk, list[float]]] = []
        for eid, rc in recovered.items():
            content_hash = hashlib.sha256(rc.text.encode("utf-8")).hexdigest()
            vec = vectors.get(content_hash)
            if vec is None:
                summary.no_vector += 1
            else:
                restorable.append((eid, rc, vec))
        summary.recoverable = len(restorable)

        if dry_run or not restorable:
            return summary

        ids = [eid for eid, _, _ in restorable]
        embeddings = [vec for _, _, vec in restorable]
        documents = [rc.text for _, rc, _ in restorable]
        metadatas = [rc.metadata for _, rc, _ in restorable]
        try:
            await vector_store.upsert_documents(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
            summary.restored = len(ids)
            logger.warning(
                "chunk-recovery: restored %d lost chunk(s) from cache + dead "
                "segments (no re-embed). %d still unrecoverable (no_text=%d, "
                "no_vector=%d) — need a source re-index.",
                summary.restored,
                summary.no_text + summary.no_vector,
                summary.no_text,
                summary.no_vector,
            )
        except Exception as exc:  # noqa: BLE001 — a failed write must close the gate
            summary.missed = len(ids)
            summary.error = f"recovery upsert failed: {exc}"
            logger.warning("chunk-recovery: upsert failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 — never raise; close the gate on error
        summary.error = str(exc)
        logger.warning("chunk-recovery: aborted: %s", exc)
    return summary
