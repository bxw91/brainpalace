"""Chunk eviction service for incremental indexing.

This module provides the ChunkEvictionService which computes the diff
between the current filesystem state and the prior folder manifest,
deletes stale chunks from the storage backend, and returns the set of
files that need (re-)indexing.

Satisfies: EVICT-02, EVICT-03, EVICT-04, EVICT-05, EVICT-07.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

from .manifest_tracker import (
    EvictionSummary,
    ManifestTracker,
    compute_file_checksum,
)

if TYPE_CHECKING:
    from brainpalace_server.config.indexing_config import IndexingConfig
    from brainpalace_server.storage.protocol import StorageBackendProtocol

logger = logging.getLogger(__name__)


class ChunkEvictionService:
    """Computes manifest diff and evicts stale chunks from storage.

    Accepts a ManifestTracker and a StorageBackendProtocol. On each call
    to compute_diff_and_evict(), it:

    1. Loads the prior manifest (if any)
    2. Computes which files are added, changed, deleted, or unchanged
    3. Bulk-evicts chunk IDs for deleted and changed files
    4. Returns an EvictionSummary and the list of files to (re-)index

    Force mode skips the diff and evicts ALL prior chunks, returning all
    current files for full reindexing.
    """

    def __init__(
        self,
        manifest_tracker: ManifestTracker,
        storage_backend: StorageBackendProtocol,
    ) -> None:
        """Initialize ChunkEvictionService.

        Args:
            manifest_tracker: ManifestTracker for loading/deleting manifests
            storage_backend: Storage backend for bulk chunk deletion
        """
        self._manifest = manifest_tracker
        self._storage = storage_backend

    async def compute_diff_and_evict(
        self,
        folder_path: str,
        current_files: list[str],
        force: bool = False,
        indexing_config: IndexingConfig | None = None,
        defer_changed_eviction: bool = False,
    ) -> tuple[EvictionSummary, list[str]]:
        """Compute manifest diff, evict stale chunks, return files to index.

        Args:
            folder_path: Absolute path to the indexed folder
            current_files: Absolute paths of files currently on disk
            force: If True, evict all prior chunks and return all current
                   files for full reindexing (bypasses diff + the re-embed
                   cooldown — the user asked for a fresh index)
            indexing_config: Phase L re-embed-guard knobs. When None, loaded
                   from the project config. Bypassed entirely under ``force``.
            defer_changed_eviction: Atomic add-then-swap. When True, the old
                   chunks of CHANGED files are NOT deleted here — they are
                   returned in ``EvictionSummary.deferred_evict_ids`` for the
                   caller to delete only after the new chunks upsert, so a crash
                   mid-reindex can't lose data. DELETED-file chunks are always
                   evicted now (their source is gone — nothing to protect).

        Returns:
            Tuple of (EvictionSummary, files_to_index) where files_to_index
            is the subset of current_files that need (re-)indexing.
        """
        if force:
            return await self._handle_force(folder_path, current_files)

        if indexing_config is None:
            # Pure defaults — no filesystem IO here (the caller passes the
            # project-loaded config). Keeps the diff path side-effect-free.
            from brainpalace_server.config.indexing_config import IndexingConfig

            indexing_config = IndexingConfig()

        prior = await self._manifest.load(folder_path)
        if prior is None:
            # No manifest: treat all files as new (first-time indexing)
            logger.debug(
                f"No manifest found for {folder_path} — treating all "
                f"{len(current_files)} files as new"
            )
            return (
                EvictionSummary(
                    files_added=list(current_files),
                    files_changed=[],
                    files_deleted=[],
                    files_unchanged=[],
                    chunks_evicted=0,
                    chunks_to_create=len(current_files),
                ),
                list(current_files),
            )

        return await self._compute_incremental_diff(
            folder_path,
            current_files,
            prior,
            indexing_config,
            defer_changed_eviction=defer_changed_eviction,
        )

    async def _handle_force(
        self,
        folder_path: str,
        current_files: list[str],
    ) -> tuple[EvictionSummary, list[str]]:
        """Handle force mode: evict all prior chunks, return all files.

        Args:
            folder_path: Absolute path to the indexed folder
            current_files: Absolute paths of files currently on disk

        Returns:
            Tuple of (EvictionSummary, current_files)
        """
        prior = await self._manifest.load(folder_path)
        chunks_evicted = 0
        if prior:
            all_prior_ids = [
                cid for rec in prior.files.values() for cid in rec.chunk_ids
            ]
            if all_prior_ids:
                chunks_evicted = await self._storage.delete_by_ids(all_prior_ids)
                logger.info(
                    f"Force mode: evicted {chunks_evicted} chunks for {folder_path}"
                )
            await self._manifest.delete(folder_path)

        return (
            EvictionSummary(
                files_added=list(current_files),
                files_changed=[],
                files_deleted=[],
                files_unchanged=[],
                chunks_evicted=chunks_evicted,
                chunks_to_create=len(current_files),
            ),
            list(current_files),
        )

    async def _compute_incremental_diff(
        self,
        folder_path: str,
        current_files: list[str],
        prior: object,
        indexing_config: IndexingConfig,
        defer_changed_eviction: bool = False,
    ) -> tuple[EvictionSummary, list[str]]:
        """Compute incremental diff against prior manifest.

        Args:
            folder_path: Absolute path to the indexed folder
            current_files: Absolute paths of files currently on disk
            prior: Prior FolderManifest loaded from disk
            indexing_config: Phase L re-embed-guard knobs (cooldown + thresholds)

        Returns:
            Tuple of (EvictionSummary, files_to_index)
        """
        from .manifest_tracker import FolderManifest

        assert isinstance(prior, FolderManifest)

        current_set = set(current_files)
        prior_set = set(prior.files.keys())

        cooldown = indexing_config.reembed_cooldown_seconds
        now = time.time()

        files_deleted = list(prior_set - current_set)
        files_unchanged: list[str] = []
        files_added: list[str] = []
        files_changed: list[str] = []
        files_deferred: list[str] = []
        files_to_index: list[str] = []

        for fp in current_files:
            if fp not in prior_set:
                files_added.append(fp)
                files_to_index.append(fp)
            else:
                prior_rec = prior.files[fp]
                try:
                    stat_result = os.stat(fp)
                    current_mtime = stat_result.st_mtime
                except OSError:
                    # File disappeared between scan and stat — treat as deleted
                    files_deleted.append(fp)
                    continue

                if current_mtime == prior_rec.mtime:
                    # mtime unchanged — assume content unchanged (skip checksum)
                    files_unchanged.append(fp)
                else:
                    # mtime changed — verify by content checksum
                    current_checksum = await asyncio.to_thread(
                        compute_file_checksum, fp
                    )
                    if current_checksum == prior_rec.checksum:
                        # Content same despite mtime change (touch, git checkout etc.)
                        files_unchanged.append(fp)
                    elif self._defer_large_reembed(
                        fp, prior_rec, stat_result, indexing_config, now, cooldown
                    ):
                        # Phase L: a LARGE file changing inside the cooldown is
                        # deferred — existing chunks kept, prior record preserved
                        # (by the caller) so it re-checks the cooldown next run.
                        files_deferred.append(fp)
                    else:
                        files_changed.append(fp)
                        files_to_index.append(fp)

        # Split the stale ids by reason: DELETED-file chunks have no replacement
        # coming, so evict them now; CHANGED-file chunks have new content about
        # to be upserted, so (when deferring) hold their eviction until after the
        # new chunks land — the atomic add-then-swap that prevents data loss on a
        # crash between evict and upsert.
        deleted_ids: list[str] = []
        for fp in files_deleted:
            if fp in prior.files:
                deleted_ids.extend(prior.files[fp].chunk_ids)
        changed_ids: list[str] = []
        for fp in files_changed:
            if fp in prior.files:
                changed_ids.extend(prior.files[fp].chunk_ids)

        if defer_changed_eviction:
            ids_to_evict_now = deleted_ids
            deferred_evict_ids = changed_ids
        else:
            ids_to_evict_now = deleted_ids + changed_ids
            deferred_evict_ids = []

        chunks_evicted = 0
        if ids_to_evict_now:
            chunks_evicted = await self._storage.delete_by_ids(ids_to_evict_now)

        deferred_note = (
            f" !{len(files_deferred)} deferred (re-embed cooldown)"
            if files_deferred
            else ""
        )
        swap_note = (
            f" [{len(deferred_evict_ids)} changed-chunk evictions held for "
            "post-upsert swap]"
            if deferred_evict_ids
            else ""
        )
        logger.info(
            f"Manifest diff for {folder_path}: "
            f"+{len(files_added)} added "
            f"~{len(files_changed)} changed "
            f"-{len(files_deleted)} deleted "
            f"={len(files_unchanged)} unchanged, "
            f"{chunks_evicted} chunks evicted{deferred_note}{swap_note}"
        )

        return (
            EvictionSummary(
                files_added=files_added,
                files_changed=files_changed,
                files_deleted=files_deleted,
                files_unchanged=files_unchanged,
                chunks_evicted=chunks_evicted,
                chunks_to_create=len(files_to_index),
                files_deferred=files_deferred,
                deferred_evict_ids=deferred_evict_ids,
            ),
            files_to_index,
        )

    @staticmethod
    def _defer_large_reembed(
        fp: str,
        prior_rec: object,
        stat_result: object,
        indexing_config: IndexingConfig,
        now: float,
        cooldown: int,
    ) -> bool:
        """Return True if a changed file is LARGE and still within its cooldown.

        Large = current byte size >= ``max_file_bytes_throttle`` OR the prior
        chunk-count >= ``big_file_chunks``. A file with no recorded
        ``last_embedded_at`` (legacy manifest / first index) is never deferred —
        it must embed once to be indexed at all.
        """
        if cooldown <= 0:
            return False
        last_embedded_at = getattr(prior_rec, "last_embedded_at", 0.0)
        if not last_embedded_at:
            return False
        size_bytes = getattr(stat_result, "st_size", 0)
        prior_chunk_count = len(getattr(prior_rec, "chunk_ids", []))
        is_large = (
            size_bytes >= indexing_config.max_file_bytes_throttle
            or prior_chunk_count >= indexing_config.big_file_chunks
        )
        if not is_large:
            return False
        if now - last_embedded_at >= cooldown:
            return False
        logger.warning(
            "Deferring re-embed of large file %s (%d chunks, %d bytes): changed "
            "%.0fs ago but within the %ds re-embed cooldown — keeping existing "
            "chunks. Exclude it if it is generated/low-value.",
            fp,
            prior_chunk_count,
            size_bytes,
            now - last_embedded_at,
            cooldown,
        )
        return True
