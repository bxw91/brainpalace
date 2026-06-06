"""Startup reconcile heals manifest/store drift automatically on server start.

No flags, no reindex: recompute each folder's chunk_count from the authoritative
per-file manifest and purge store chunks the manifest no longer references
(orphans left by past corruption, e.g. a duplicate server). No-op when nothing
drifted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from brainpalace_server.services.folder_manager import FolderManager
from brainpalace_server.services.manifest_tracker import (
    FileRecord,
    FolderManifest,
    ManifestTracker,
)
from brainpalace_server.services.startup_reconcile import reconcile_folders


def _storage(deleted: int = 0) -> AsyncMock:
    s = AsyncMock()
    s.delete_by_ids = AsyncMock(return_value=deleted)
    return s


async def _seed(tmp_path, folder, chunk_ids, count, manifest_files, *, watch="auto"):
    fm = FolderManager(state_dir=tmp_path)
    await fm.initialize()
    await fm.add_folder(
        folder_path=folder,
        chunk_count=count,
        chunk_ids=chunk_ids,
        watch_mode=watch,
        include_code=True,
    )
    mt = ManifestTracker(manifests_dir=tmp_path / "manifests")
    if manifest_files is not None:
        man = FolderManifest(folder_path=folder)
        for fp, ids in manifest_files.items():
            man.files[fp] = FileRecord(checksum="x", mtime=1.0, chunk_ids=ids)
        await mt.save(man)
    return fm, mt


@pytest.mark.asyncio
async def test_reconcile_heals_inflated_count_and_purges_orphans(tmp_path):
    folder = str(tmp_path / "repo")
    # FolderManager says 5 chunks incl. 2 orphans; manifest truth = a,b,c.
    fm, mt = await _seed(
        tmp_path,
        folder,
        chunk_ids=["a", "b", "c", "orphan1", "orphan2"],
        count=5,
        manifest_files={f"{folder}/x.py": ["a", "b"], f"{folder}/y.py": ["c"]},
    )
    storage = _storage(deleted=2)

    summary = await reconcile_folders(fm, mt, storage)

    # Orphans purged from the store.
    storage.delete_by_ids.assert_awaited_once()
    assert sorted(storage.delete_by_ids.call_args[0][0]) == ["orphan1", "orphan2"]
    # FolderManager count healed to truth.
    rec = await fm.get_folder(folder)
    assert rec.chunk_count == 3
    assert sorted(rec.chunk_ids) == ["a", "b", "c"]
    # Settings preserved.
    assert rec.watch_mode == "auto"
    assert rec.include_code is True
    # Summary.
    assert summary.folders_healed == 1
    assert summary.chunks_purged == 2


@pytest.mark.asyncio
async def test_reconcile_noop_when_consistent(tmp_path):
    folder = str(tmp_path / "repo")
    fm, mt = await _seed(
        tmp_path,
        folder,
        chunk_ids=["a", "b", "c"],
        count=3,
        manifest_files={f"{folder}/x.py": ["a", "b"], f"{folder}/y.py": ["c"]},
    )
    storage = _storage()

    summary = await reconcile_folders(fm, mt, storage)

    storage.delete_by_ids.assert_not_called()
    assert summary.folders_healed == 0
    assert summary.chunks_purged == 0


@pytest.mark.asyncio
async def test_reconcile_skips_folder_without_manifest(tmp_path):
    """No per-file manifest => no ground truth; leave the folder untouched."""
    folder = str(tmp_path / "repo")
    fm, mt = await _seed(
        tmp_path,
        folder,
        chunk_ids=["a", "b"],
        count=2,
        manifest_files=None,
    )
    storage = _storage()

    summary = await reconcile_folders(fm, mt, storage)

    storage.delete_by_ids.assert_not_called()
    rec = await fm.get_folder(folder)
    assert rec.chunk_count == 2  # untouched
    assert summary.folders_healed == 0
