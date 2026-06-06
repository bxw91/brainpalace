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

import logging
from dataclasses import dataclass, field
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
