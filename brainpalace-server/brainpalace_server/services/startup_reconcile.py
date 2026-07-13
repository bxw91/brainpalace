"""Startup folder reconciliation — self-heal manifest/store drift on server start.

Runs once during server startup (lifespan). For every indexed folder it:

  1. recomputes the folder's chunk-id set from the authoritative per-file
     manifest (retains unchanged files, drops deleted/changed-old chunks), and
  2. purges store chunks the manifest no longer references — orphans left behind
     by past corruption such as a duplicate server writing the shared data dir.

It is a no-op when a folder is already consistent, so healthy projects pay
nothing. It never re-embeds or reindexes: the heal is pure bookkeeping +
targeted deletes. BM25 (a full-rebuild index keyed by chunk id) needs no rebuild
here — any stale id it still holds simply yields an empty store fetch that the
query layer drops; it converges on the next index.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brainpalace_server.services import chunk_recovery

logger = logging.getLogger(__name__)


@dataclass
class ReconcileSummary:
    """Outcome of a startup reconciliation sweep."""

    folders_checked: int = 0
    folders_healed: int = 0
    chunks_purged: int = 0
    healed_folders: list[str] = field(default_factory=list)


def _authoritative_ids(manifest: Any) -> list[str]:
    """Sorted union of chunk ids across the current per-file manifest records."""
    ids: set[str] = set()
    for rec in manifest.files.values():
        ids.update(rec.chunk_ids)
    return sorted(ids)


@dataclass
class StoreReconcileSummary:
    """Outcome of the store→manifest reconcile (lost-chunk detection).

    ``files_dropped`` counts files NEWLY marked ``pending_reindex`` this run
    (name kept for event-log/status compatibility). ``pending_folders`` lists
    folders that still carry marks from a previous run whose reindex hasn't
    landed yet — the caller re-enqueues those too, so a failed/crashed reindex
    is retried on every start.
    """

    folders_checked: int = 0
    folders_repaired: int = 0
    files_dropped: int = 0
    repaired_folders: list[str] = field(default_factory=list)
    files_pending: int = 0
    pending_folders: list[str] = field(default_factory=list)


async def reconcile_store_against_manifest(
    folder_manager: Any,
    manifest_tracker: Any,
    storage_backend: Any,
) -> StoreReconcileSummary:
    """Mark manifest file records whose chunks the STORE has lost, so they re-index.

    The inverse of :func:`reconcile_folders`: that trusts the manifest and
    purges the store; this trusts the store's *existence*. For every tracked
    folder it asks the backend which of the manifest's chunk ids still exist,
    and flags any file whose chunks are (partly or fully) gone with
    ``pending_reindex`` — the eviction diff then forces a reindex regardless of
    mtime/checksum, and the add-then-swap pipeline replaces the record only
    after the new chunks are safely upserted (**drop-after-verify**).

    The record and its surviving chunk ids are KEPT, never deleted: stage-1
    recovery keeps wanting the missing chunks on every start, and deep-clean's
    manifest-orphan sweep keeps sparing the survivors. A failed reindex or a
    crash in the window loses nothing — the mark persists and retries.

    This makes silent vector-store loss (a corrupt/healed HNSW that shed live
    vectors, a duplicate-server stomp) **detectable and self-repairing** instead
    of permanently invisible: without it the manifest keeps claiming chunks that
    no longer exist, so incremental indexing sees "unchanged" and never heals.

    **It never deletes store chunks** — pure manifest bookkeeping — and never
    re-embeds here (the actual re-index happens on the next normal run). No-op
    when the backend can't answer existence or every folder is consistent.
    """
    summary = StoreReconcileSummary()
    if folder_manager is None or manifest_tracker is None or storage_backend is None:
        return summary
    get_existing = getattr(storage_backend, "get_existing_ids", None)
    if get_existing is None:
        return summary  # backend can't answer existence → skip safely

    for rec in await folder_manager.list_folders():
        summary.folders_checked += 1
        manifest = await manifest_tracker.load(rec.folder_path)
        if manifest is None or not manifest.files:
            continue
        all_ids = _authoritative_ids(manifest)
        if not all_ids:
            continue

        try:
            present = await get_existing(all_ids)
        except Exception as exc:  # noqa: BLE001 — never fail startup on the probe
            logger.warning(
                "reconcile(store): existence probe failed for %s: %s",
                rec.folder_path,
                exc,
            )
            continue

        # A file is "lost" if ANY of its chunks is missing from the store.
        lost_files = [
            fp
            for fp, frec in manifest.files.items()
            if frec.chunk_ids
            and not frec.pending_reindex
            and not set(frec.chunk_ids).issubset(present)
        ]
        # Marks left by a previous run (reindex failed / crashed mid-window):
        # nothing to re-mark, but the folder must be re-enqueued for retry.
        already_pending = sum(
            1 for frec in manifest.files.values() if frec.pending_reindex
        )
        if already_pending:
            summary.files_pending += already_pending
            summary.pending_folders.append(rec.folder_path)
        if not lost_files:
            continue

        for fp in lost_files:
            manifest.files[fp].pending_reindex = True
        try:
            await manifest_tracker.save(manifest)
            authoritative = _authoritative_ids(manifest)
            await folder_manager.add_folder(
                folder_path=rec.folder_path,
                chunk_count=len(authoritative),
                chunk_ids=authoritative,
                watch_mode=rec.watch_mode,
                watch_debounce_seconds=rec.watch_debounce_seconds,
                include_code=rec.include_code,
                source="reconcile-store",
                domain=rec.domain,
                authority=rec.authority,
            )
        except Exception as exc:  # noqa: BLE001 — never fail startup on a heal
            logger.warning(
                "reconcile(store): failed to mark manifest for %s: %s",
                rec.folder_path,
                exc,
            )
            continue

        summary.folders_repaired += 1
        summary.files_dropped += len(lost_files)
        summary.repaired_folders.append(rec.folder_path)
        logger.warning(
            "reconcile(store): %s lost chunks for %d file(s) — marked "
            "pending_reindex; records kept until the reindex verifies "
            "(manifest claimed %d chunks, store has %d)",
            rec.folder_path,
            len(lost_files),
            len(all_ids),
            len(present),
        )

    if summary.folders_repaired:
        logger.warning(
            "Startup store-reconcile: %d/%d folder(s) had lost chunks; marked "
            "%d file record(s) pending_reindex (kept until reindex verifies).",
            summary.folders_repaired,
            summary.folders_checked,
            summary.files_dropped,
        )
    return summary


@dataclass
class DeepCleanSummary:
    """Outcome of the manifest-orphan cleanup + missing-folder prune."""

    folders_removed: int = 0
    removed_folders: list[str] = field(default_factory=list)
    folder_chunks_evicted: int = 0
    orphan_chunks_removed: int = 0
    session_chunks_removed: int = 0
    git_chunks_removed: int = 0
    skipped_reason: str | None = None


async def prune_orphan_session_chunks(
    storage_backend: Any,
    archive_dir: Any,
    summary: DeepCleanSummary,
) -> None:
    """Delete ``session_turn`` chunks whose source transcript is gone from disk.

    Existence-based, not age-based: a session chunk is an orphan exactly when the
    file it was indexed from no longer exists (curated away, archive cleared,
    deleted). SAFETY: if ``archive_dir`` is provided but absent, skip entirely —
    we can't tell "no sessions" from "archive temporarily unmounted" and must not
    wipe everything. Chunks with no recorded source are left alone. Never raises.
    """
    import os

    get_pairs = getattr(storage_backend, "get_id_source_pairs", None)
    if storage_backend is None or get_pairs is None:
        return
    if archive_dir is not None and not Path(archive_dir).exists():
        return
    try:
        pairs = await get_pairs({"source_type": "session_turn"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("session-clean: enumerate failed: %s", exc)
        return

    by_source: dict[str, list[str]] = {}
    for cid, src in pairs:
        by_source.setdefault(src, []).append(cid)
    orphan_ids: list[str] = []
    for src, ids in by_source.items():
        # Empty source → can't verify existence → leave it.
        if src and not os.path.exists(src):
            orphan_ids.extend(ids)
    if not orphan_ids:
        return
    try:
        removed = await storage_backend.delete_by_ids(orphan_ids)
        summary.session_chunks_removed += int(removed or 0)
        logger.warning(
            "session-clean: removed %d session chunk(s) whose transcript is gone",
            int(removed or 0),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("session-clean: delete failed: %s", exc)


def _current_git_shas(repo_path: str) -> set[str] | None:
    """All commit shas reachable in the repo (``git rev-list --all``), or None.

    None means "couldn't determine" (not a repo / git error) → caller must NOT
    purge. An empty set is a valid answer (history wiped) and DOES purge.
    """
    import subprocess

    from brainpalace_server.indexing.git_loader import git_toplevel

    top = git_toplevel(repo_path)
    if top is None:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(top), "rev-list", "--all"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("git-clean: rev-list failed: %s", exc)
        return None
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def _indexable_git_shas(
    repo_path: str, config: Any = None, git_state_dir: Any = None
) -> set[str] | None:
    """Shas the git indexer has actually recorded as indexed — the self-heal
    WANTED scope.

    Bounded by the git indexer's own persisted progress, not the live branch
    tip: mirrors the indexer's depth cap + monorepo path scope (via
    ``resolve_commit_scope``) AND walks from its recorded ``last_sha`` instead
    of HEAD. Self-heal runs at startup, before the async git-history index job
    has necessarily run — wanting every HEAD commit back would count
    never-yet-indexed commits as lost. No recorded ``last_sha`` (git never
    indexed this repo, or no state dir given) means nothing has been indexed
    yet, so nothing can be lost: want zero, matching the empty-manifest folder
    case. A recorded ``last_sha`` that's no longer reachable (e.g. GC'd after
    a history rewrite) makes the underlying ``git log`` fail, which correctly
    propagates as ``None`` (couldn't determine). Disabled git indexing wants
    nothing. The deep-clean keep-set (:func:`_current_git_shas`) intentionally
    stays ``--all`` — never delete chunks of commits that still exist on any
    ref; that side is untouched by this scoping.
    """
    from brainpalace_server.config.git_config import load_git_indexing_config
    from brainpalace_server.indexing.git_loader import (
        list_indexable_shas,
        resolve_commit_scope,
    )
    from brainpalace_server.services.git_history_index_service import (
        load_git_last_sha,
    )

    cfg = config if config is not None else load_git_indexing_config()
    if not cfg.enabled:
        return set()
    target = cfg.repo_path or repo_path
    last_sha = load_git_last_sha(git_state_dir, target)
    if not last_sha:
        return set()
    scope = resolve_commit_scope(target, cfg.path_filter)
    return list_indexable_shas(target, depth=cfg.depth, paths=scope, rev=last_sha)


async def prune_orphan_git_chunks(
    storage_backend: Any,
    repo_path: str | None,
    summary: DeepCleanSummary,
) -> None:
    """Delete ``git_commit`` chunks whose commit no longer exists in the repo.

    Existence-based via ``git rev-list --all``: a reset, a squash/rebase, or any
    history rewrite makes the old shas unreachable → their chunks are purged. The
    chunk id is ``git_commit:<sha>``, so the sha is read straight off the id.
    SAFETY: if the repo can't be resolved (None), nothing is purged. Never raises.
    """
    get_ids = getattr(storage_backend, "get_ids_by_metadata", None)
    if storage_backend is None or get_ids is None or not repo_path:
        return
    try:
        stored = await get_ids({"source_type": "git_commit"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("git-clean: enumerate failed: %s", exc)
        return
    if not stored:
        return
    current = await asyncio.to_thread(_current_git_shas, repo_path)
    if current is None:
        return  # not a repo / git error → never purge on uncertainty

    orphan = [cid for cid in stored if cid.split("git_commit:", 1)[-1] not in current]
    if not orphan:
        return
    try:
        removed = await storage_backend.delete_by_ids(orphan)
        summary.git_chunks_removed += int(removed or 0)
        logger.warning(
            "git-clean: removed %d git_commit chunk(s) for commits no longer in "
            "the repo (reset/rewrite)",
            int(removed or 0),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("git-clean: delete failed: %s", exc)


async def prune_missing_folders(
    folder_manager: Any,
    manifest_tracker: Any,
    storage_backend: Any,
    summary: DeepCleanSummary,
) -> None:
    """Drop folders whose directory no longer exists: evict chunks + manifest.

    A removed source directory leaves its chunks, manifest, and folder record
    behind forever. For each tracked folder whose path is gone from disk this
    evicts the folder's chunks (authoritative manifest ids, else the folder
    record's ids), deletes the manifest, and removes the folder record. Never
    raises — a per-folder failure is logged and skipped.
    """
    import os

    if folder_manager is None or storage_backend is None:
        return
    for rec in await folder_manager.list_folders():
        if os.path.exists(rec.folder_path):
            continue
        ids: list[str] = list(rec.chunk_ids)
        if manifest_tracker is not None:
            manifest = await manifest_tracker.load(rec.folder_path)
            if manifest is not None and manifest.files:
                ids = _authoritative_ids(manifest)
        try:
            if ids:
                evicted = await storage_backend.delete_by_ids(ids)
                summary.folder_chunks_evicted += int(evicted or 0)
            if manifest_tracker is not None:
                await manifest_tracker.delete(rec.folder_path)
            await folder_manager.remove_folder(rec.folder_path)
        except Exception as exc:  # noqa: BLE001 — never fail on a single folder
            logger.warning(
                "deep-clean: failed to prune missing folder %s: %s",
                rec.folder_path,
                exc,
            )
            continue
        summary.folders_removed += 1
        summary.removed_folders.append(rec.folder_path)
        logger.warning(
            "deep-clean: folder gone from disk — removed %s (%d chunk(s) evicted)",
            rec.folder_path,
            len(ids),
        )


async def reconcile_orphan_chunks(
    folder_manager: Any,
    manifest_tracker: Any,
    storage_backend: Any,
    summary: DeepCleanSummary,
) -> None:
    """Delete live ``code``/``doc`` chunks referenced by no folder manifest.

    The global complement to :func:`reconcile_folders` (which only purges a
    folder's *own* drifted chunks): a chunk that belongs to no manifest at all
    (a removed folder, a superseded content-hash id, a partial-crash leftover)
    is an orphan. Scope is hard-limited to ``source_type in {code, doc}`` so it
    can NEVER touch ``session_turn`` / ``git_commit`` chunks (which folder
    manifests don't track) or the separate memory collection.

    SAFETY: if the manifest union is empty (manifests not yet written / first
    boot) it refuses to delete — otherwise it would wipe a freshly-built index.
    Caller must also gate this on "no indexing in progress". Never raises.
    """
    if folder_manager is None or manifest_tracker is None or storage_backend is None:
        return
    get_ids = getattr(storage_backend, "get_ids_by_metadata", None)
    if get_ids is None:
        return  # backend can't enumerate ids → skip safely

    # Union of every folder manifest's authoritative chunk ids = the legitimate
    # set of folder-indexed chunks.
    authoritative: set[str] = set()
    for rec in await folder_manager.list_folders():
        manifest = await manifest_tracker.load(rec.folder_path)
        if manifest is not None:
            authoritative.update(_authoritative_ids(manifest))

    try:
        store_ids = await get_ids({"source_type": {"$in": ["code", "doc"]}})
    except Exception as exc:  # noqa: BLE001 — never fail on the enumerate probe
        logger.warning("deep-clean: code/doc id enumeration failed: %s", exc)
        return

    orphans = sorted(store_ids - authoritative)
    if not orphans:
        return
    # Refuse to delete the whole index when there's nothing authoritative to
    # compare against (manifests missing) — that's a not-ready state, not orphans.
    if not authoritative:
        summary.skipped_reason = (
            f"{len(orphans)} unreferenced code/doc chunk(s) but no manifest "
            "union — refusing to delete (index not ready)"
        )
        logger.warning("deep-clean: %s", summary.skipped_reason)
        return

    try:
        removed = await storage_backend.delete_by_ids(orphans)
        summary.orphan_chunks_removed += int(removed or 0)
        logger.warning(
            "deep-clean: removed %d orphan code/doc chunk(s) referenced by no "
            "manifest (store had %d, manifests reference %d)",
            int(removed or 0),
            len(store_ids),
            len(authoritative),
        )
    except Exception as exc:  # noqa: BLE001 — never fail on the delete
        logger.warning("deep-clean: orphan-chunk delete failed: %s", exc)


async def deep_clean(
    folder_manager: Any,
    manifest_tracker: Any,
    storage_backend: Any,
    archive_dir: Any = None,
    repo_path: str | None = None,
) -> DeepCleanSummary:
    """Run every existence-based purge: each source type against its own truth.

    Order matters: prune missing folders first (drops their manifests + chunks),
    so the subsequent code/doc orphan sweep sees the reduced manifest union and
    reaps any now-unreferenced chunks the prune didn't catch. Then the
    independently-scoped session and git purges run (each against the live files /
    repo, not the folder manifests). Caller MUST ensure no indexing is in progress
    (a mid-index store is transiently inconsistent).
    """
    summary = DeepCleanSummary()
    await prune_missing_folders(
        folder_manager, manifest_tracker, storage_backend, summary
    )
    await reconcile_orphan_chunks(
        folder_manager, manifest_tracker, storage_backend, summary
    )
    await prune_orphan_session_chunks(storage_backend, archive_dir, summary)
    await prune_orphan_git_chunks(storage_backend, repo_path, summary)
    return summary


async def reconcile_folders(
    folder_manager: Any,
    manifest_tracker: Any,
    storage_backend: Any,
) -> ReconcileSummary:
    """Heal folder counts and purge store orphans for every tracked folder.

    Args:
        folder_manager: FolderManager (folder-level chunk_id records).
        manifest_tracker: ManifestTracker (authoritative per-file records).
        storage_backend: storage backend exposing ``delete_by_ids``.

    Returns:
        ReconcileSummary describing what was healed.
    """
    summary = ReconcileSummary()
    if folder_manager is None or manifest_tracker is None or storage_backend is None:
        return summary

    folders = await folder_manager.list_folders()
    for rec in folders:
        summary.folders_checked += 1

        manifest = await manifest_tracker.load(rec.folder_path)
        if manifest is None:
            # No per-file ground truth — don't guess, leave it alone.
            continue

        authoritative = _authoritative_ids(manifest)
        auth_set = set(authoritative)
        prior_ids = set(rec.chunk_ids)
        orphans = sorted(prior_ids - auth_set)

        drift = (
            bool(orphans)
            or rec.chunk_count != len(authoritative)
            or prior_ids != auth_set
        )
        if not drift:
            continue

        if orphans:
            try:
                purged = await storage_backend.delete_by_ids(orphans)
                summary.chunks_purged += int(purged or 0)
            except Exception as exc:  # noqa: BLE001 — never fail startup on a heal
                logger.warning(
                    "reconcile: failed to purge %d orphan chunk(s) for %s: %s",
                    len(orphans),
                    rec.folder_path,
                    exc,
                )

        try:
            await folder_manager.add_folder(
                folder_path=rec.folder_path,
                chunk_count=len(authoritative),
                chunk_ids=authoritative,
                watch_mode=rec.watch_mode,
                watch_debounce_seconds=rec.watch_debounce_seconds,
                include_code=rec.include_code,
                source="reconcile",
                domain=rec.domain,
                authority=rec.authority,
            )
        except Exception as exc:  # noqa: BLE001 — never fail startup on a heal
            logger.warning(
                "reconcile: failed to update folder record for %s: %s",
                rec.folder_path,
                exc,
            )
            continue

        summary.folders_healed += 1
        summary.healed_folders.append(rec.folder_path)
        logger.info(
            "reconcile: healed %s (chunk_count %d -> %d, purged %d orphan chunk(s))",
            rec.folder_path,
            rec.chunk_count,
            len(authoritative),
            len(orphans),
        )

    if summary.folders_healed:
        logger.info(
            "Startup reconcile: healed %d/%d folder(s), purged %d orphan chunk(s)",
            summary.folders_healed,
            summary.folders_checked,
            summary.chunks_purged,
        )
    return summary


def _manifest_union(folders_with_manifests: list[Any]) -> set[str]:
    """Union of authoritative chunk ids across every folder manifest."""
    ids: set[str] = set()
    for manifest in folders_with_manifests:
        if manifest is not None:
            ids.update(_authoritative_ids(manifest))
    return ids


async def _enqueue_folder_reindex(
    job_service: Any, folder_manager: Any, folders: list[str]
) -> int:
    """Enqueue an incremental index job per folder so dropped files reindex.

    Mirrors the file-watcher enqueue (``force=False`` → relies on the manifest
    for incremental, so only the dropped/new files are processed). Embeddings
    come from the cache; only the genuinely-gone residue calls the provider.
    Never raises — a per-folder failure is logged and skipped.
    """
    from brainpalace_server.models.index import IndexRequest  # lazy: avoid cycle

    enqueued = 0
    for folder_path in folders:
        try:
            rec = await folder_manager.get_folder(folder_path)
            include_code = rec.include_code if rec is not None else True
            request = IndexRequest(
                folder_path=folder_path,
                include_code=include_code,
                recursive=True,
                force=False,
                trigger="self-heal",
            )
            await job_service.enqueue_job(
                request=request,
                operation="index",
                force=False,
                allow_external=True,
                source="self-heal",
            )
            enqueued += 1
        except Exception as exc:  # noqa: BLE001 — never fail heal on a single folder
            logger.warning(
                "self-heal: failed to enqueue reindex for %s: %s", folder_path, exc
            )
    if enqueued:
        logger.warning(
            "self-heal: enqueued incremental reindex for %d folder(s) to restore "
            "dropped/lost files (post-deep_clean).",
            enqueued,
        )
    return enqueued


async def self_heal_on_startup(
    *,
    folder_manager: Any,
    manifest_tracker: Any,
    storage_backend: Any,
    vector_store: Any,
    cache_db_path: Any,
    target_dimensions: int,
    bm25_manager: Any = None,
    repo_path: str | None = None,
    git_state_dir: Any = None,
    job_service: Any = None,
    read_only: bool = False,
) -> dict[str, Any]:
    """Recover lost chunks FIRST, then gate the destructive deep_clean on success.

    Order and gating (the data-safety contract):

      1. **Recover** the manifest's missing chunks from dead segments + the
         embedding cache — constructive, no re-embed (:mod:`chunk_recovery`).
      2. **reconcile_folders** — heal folder counts / drop folder-record orphans
         the manifest no longer references (its purge can never touch a restored
         chunk, which is in the manifest).
      3. **deep_clean** — destructive existence-based purges — runs **only if
         recovery fully succeeded** (``RecoverySummary.complete``): no error and
         every *possible* chunk (dead-text + cache-vector) restored. A failed or
         partial recovery keeps the gate CLOSED so we never delete on an
         unrecovered store. When recovery is not applicable (no vector store / no
         manifest ids) the gate defaults open, preserving prior behavior.

    Never raises — a failure is logged and leaves the gate closed.
    """
    report: dict[str, Any] = {
        "recovery": None,
        "deep_clean_ran": False,
        "deep_clean_skipped_reason": None,
        "bm25_rebuilt": 0,
        "files_dropped": 0,
        "dropped_folders": [],
        "reindex_enqueued": 0,
    }

    # Build the manifest union (what the index *should* contain for code/doc).
    manifest_ids: set[str] = set()
    if folder_manager is not None and manifest_tracker is not None:
        manifests = []
        for rec in await folder_manager.list_folders():
            manifests.append(await manifest_tracker.load(rec.folder_path))
        manifest_ids = _manifest_union(manifests)

    # Add the git plane: every commit the git indexer has already recorded as
    # indexed (its persisted last_sha) should have a git_commit chunk. Git
    # chunks live in the same collection + embedding cache, so a lost commit
    # recovers from cache+dead exactly like code/doc — but git isn't
    # manifest-tracked, so we source its wanted ids from the repo itself,
    # bounded by the indexer's own progress (last_sha + monorepo path filter,
    # not HEAD, not --all): a commit the async git-history job hasn't reached
    # yet was never lost, so it must not count as residue.
    git_ids: set[str] = set()
    if repo_path:
        shas = _indexable_git_shas(repo_path, git_state_dir=git_state_dir)
        if shas:
            git_ids = {f"git_commit:{sha}" for sha in shas}

    wanted = manifest_ids | git_ids

    summary: chunk_recovery.RecoverySummary | None = None
    if vector_store is not None and wanted:
        chroma_sqlite = Path(vector_store.persist_dir) / "chroma.sqlite3"
        summary = await chunk_recovery.recover_lost_chunks(
            vector_store=vector_store,
            wanted_ids=wanted,
            chroma_sqlite_path=chroma_sqlite,
            cache_db_path=cache_db_path,
            target_dimensions=target_dimensions,
            presence_state_path=Path(vector_store.persist_dir)
            / "recovery_presence.json",
        )
    report["recovery"] = summary

    # GATE: stage 2 (mutating + destructive) runs ONLY when recovery fully
    # succeeded (or was N/A) AND we are not read-only. A failed/partial recovery
    # keeps the gate CLOSED so we never drop manifest records or delete on an
    # unrecovered store. Read-only forces the gate CLOSED unconditionally:
    # stage-1 recovery (cache+dead, no network) already ran above, but we never
    # drop manifest records, delete chunks, or enqueue a reindex.
    if read_only:
        gate_open = False
        report["deep_clean_skipped_reason"] = "read-only mode"
        logger.warning(
            "self-heal: read-only — recovery ran (restored=%d) but SKIPPING "
            "stage 2 (drop/clean/reindex); no deletes, no provider calls.",
            int(getattr(summary, "restored", 0) or 0),
        )
    else:
        gate_open = summary is None or summary.complete
    if gate_open:
        # 2a. MARK manifest records for files NOT fully present in the store
        #     after recovery (fully- OR partially-missing) as pending_reindex.
        #     Records + surviving chunk ids are KEPT — recovery keeps wanting
        #     the missing chunks and deep-clean spares the survivors — and the
        #     record is replaced only when the reindex verifies
        #     (drop-after-verify via the pipeline's add-then-swap). Pure
        #     manifest bookkeeping — NO API call here. (vector_store carries
        #     the get_existing_ids probe the backend wrapper lacks.)
        drop = await reconcile_store_against_manifest(
            folder_manager, manifest_tracker, vector_store
        )
        report["files_dropped"] = drop.files_dropped
        report["dropped_folders"] = list(drop.repaired_folders)
        # 2b. Heal folder records against the updated manifests.
        await reconcile_folders(folder_manager, manifest_tracker, storage_backend)
        # 2c. Destructive existence purges. Marked files' surviving chunks stay
        #     in the manifest union, so the orphan sweep cannot touch them.
        await deep_clean(folder_manager, manifest_tracker, storage_backend)
        report["deep_clean_ran"] = True
        # 2d. AFTER deep_clean: reindex the marked files (incremental folder
        #     index; embeddings come from the cache, only the genuinely-gone
        #     residue hits the provider). Folders with marks left over from a
        #     previous failed/crashed reindex are re-enqueued too.
        reindex_folders = list(
            dict.fromkeys(drop.repaired_folders + drop.pending_folders)
        )
        if reindex_folders and job_service is not None:
            report["reindex_enqueued"] = await _enqueue_folder_reindex(
                job_service, folder_manager, reindex_folders
            )
    elif not read_only:
        assert summary is not None  # gate_open is False => summary present
        report["deep_clean_skipped_reason"] = (
            f"recovery incomplete (restored={summary.restored}/"
            f"{summary.recoverable}, missed={summary.missed}, "
            f"error={summary.error})"
        )
        logger.warning(
            "self-heal: SKIPPING stage 2 (drop/clean/reindex) — %s. Refusing "
            "destructive cleanup until lost chunks are recovered.",
            report["deep_clean_skipped_reason"],
        )

    # Restored chunks went into the vector store only; rebuild the lexical BM25
    # index from the (post-cleanup) live collection so keyword/hybrid-bm25 search
    # finds them too. No re-embed. Only when something was actually restored.
    if (
        summary is not None
        and summary.restored
        and bm25_manager is not None
        and vector_store is not None
    ):
        report["bm25_rebuilt"] = chunk_recovery.rebuild_bm25_from_collection(
            bm25_manager, vector_store
        )
    return report
