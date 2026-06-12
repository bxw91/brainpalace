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
    """Outcome of the store→manifest reconcile (lost-chunk detection)."""

    folders_checked: int = 0
    folders_repaired: int = 0
    files_dropped: int = 0
    repaired_folders: list[str] = field(default_factory=list)


async def reconcile_store_against_manifest(
    folder_manager: Any,
    manifest_tracker: Any,
    storage_backend: Any,
) -> StoreReconcileSummary:
    """Drop manifest file records whose chunks the STORE has lost, so they re-index.

    The inverse of :func:`reconcile_folders`: that trusts the manifest and
    purges the store; this trusts the store's *existence* and prunes the
    manifest. For every tracked folder it asks the backend which of the
    manifest's chunk ids still exist, and removes any file whose chunks are
    (partly or fully) gone — leaving no manifest record, so the next index run
    treats the file as new and re-creates its chunks.

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
            if frec.chunk_ids and not set(frec.chunk_ids).issubset(present)
        ]
        if not lost_files:
            continue

        for fp in lost_files:
            del manifest.files[fp]
        try:
            await manifest_tracker.save(manifest)
            survivors = _authoritative_ids(manifest)
            await folder_manager.add_folder(
                folder_path=rec.folder_path,
                chunk_count=len(survivors),
                chunk_ids=survivors,
                watch_mode=rec.watch_mode,
                watch_debounce_seconds=rec.watch_debounce_seconds,
                include_code=rec.include_code,
                source="reconcile-store",
            )
        except Exception as exc:  # noqa: BLE001 — never fail startup on a heal
            logger.warning(
                "reconcile(store): failed to prune manifest for %s: %s",
                rec.folder_path,
                exc,
            )
            continue

        summary.folders_repaired += 1
        summary.files_dropped += len(lost_files)
        summary.repaired_folders.append(rec.folder_path)
        logger.warning(
            "reconcile(store): %s lost chunks for %d file(s) — dropped from "
            "manifest so they re-index next run (manifest claimed %d chunks, "
            "store has %d)",
            rec.folder_path,
            len(lost_files),
            len(all_ids),
            len(present),
        )

    if summary.folders_repaired:
        logger.warning(
            "Startup store-reconcile: %d/%d folder(s) had lost chunks; dropped "
            "%d file record(s) for re-index.",
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
