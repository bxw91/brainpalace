"""Folder chunk_count must reflect the CURRENT set, and self-heal on deletes.

History:
  * First bug: incremental re-index overwrote the cumulative count with the
    per-run delta (undercount of unchanged files).
  * The union fix (`_merge_chunk_ids`) over-corrected: it never dropped evicted
    ids, so the persisted count grew monotonically and never shrank when files
    changed or were deleted — diverging far above the real store.

Correct contract: the folder's chunk-id set is the authoritative union over the
*current* per-file manifest records. Unchanged files are retained (carried over
in the manifest); deleted/changed-old chunks are absent (evicted, not in the
manifest), so the count self-heals.
"""

import pytest

from brainpalace_server.services.folder_manager import FolderManager
from brainpalace_server.services.indexing_service import _folder_chunk_ids
from brainpalace_server.services.manifest_tracker import FileRecord, FolderManifest


def _manifest(folder: str, files: dict[str, list[str]]) -> FolderManifest:
    m = FolderManifest(folder_path=folder)
    for fp, ids in files.items():
        m.files[fp] = FileRecord(checksum="x", mtime=1.0, chunk_ids=ids)
    return m


def test_folder_chunk_ids_unions_current_files():
    """Authoritative set = sorted union over all current file records."""
    m = _manifest("/repo", {"/repo/a.py": ["a", "b"], "/repo/b.py": ["c"]})
    assert _folder_chunk_ids(m) == ["a", "b", "c"]


def test_folder_chunk_ids_dedupes():
    m = _manifest("/repo", {"/repo/a.py": ["a", "b"], "/repo/b.py": ["b", "c"]})
    assert _folder_chunk_ids(m) == ["a", "b", "c"]


def test_folder_chunk_ids_self_heals_on_delete():
    """A file no longer in the manifest drops its chunks from the set."""
    before = _manifest("/repo", {"/repo/a.py": ["a", "b"], "/repo/gone.py": ["x", "y"]})
    assert _folder_chunk_ids(before) == ["a", "b", "x", "y"]

    # gone.py deleted -> next manifest only has a.py
    after = _manifest("/repo", {"/repo/a.py": ["a", "b"]})
    assert _folder_chunk_ids(after) == ["a", "b"]


def test_folder_chunk_ids_empty_manifest():
    assert _folder_chunk_ids(_manifest("/repo", {})) == []


@pytest.mark.asyncio
async def test_reindex_count_shrinks_when_file_deleted(tmp_path):
    """End-to-end on FolderManager: persisting the derived set shrinks the count
    when a file is removed (the old union code left it inflated forever)."""
    fm = FolderManager(state_dir=tmp_path)
    await fm.initialize()

    # Initial index: two files, 4 chunks total.
    first = _manifest("/repo", {"/repo/a.py": ["a", "b"], "/repo/b.py": ["c", "d"]})
    ids = _folder_chunk_ids(first)
    await fm.add_folder(
        folder_path="/repo", chunk_count=len(ids), chunk_ids=ids, include_code=True
    )
    rec = await fm.get_folder("/repo")
    assert rec is not None and rec.chunk_count == 4

    # b.py deleted -> reindex persists the derived (smaller) set.
    second = _manifest("/repo", {"/repo/a.py": ["a", "b"]})
    ids2 = _folder_chunk_ids(second)
    await fm.add_folder(
        folder_path="/repo", chunk_count=len(ids2), chunk_ids=ids2, include_code=True
    )
    rec = await fm.get_folder("/repo")
    assert rec is not None
    assert rec.chunk_count == 2  # self-healed, not stuck at 4
