"""Phase 2 — folder chunk_count stays cumulative across re-index.

Regression: incremental re-index chunked only the changed files and
``add_folder`` overwrote the persisted cumulative count with the per-run
delta. The fix unions the new chunk ids with the already-tracked ids so the
stored ``chunk_count`` reflects the full set the folder owns.
"""

import pytest

from brainpalace_server.services.folder_manager import FolderManager
from brainpalace_server.services.indexing_service import _merge_chunk_ids


def test_merge_chunk_ids_unions_and_dedupes():
    existing = ["a", "b", "c", "d", "e"]
    new = ["e", "f"]  # 'e' overlaps, 'f' is new
    assert _merge_chunk_ids(existing, new) == ["a", "b", "c", "d", "e", "f"]


def test_merge_chunk_ids_empty_existing():
    assert _merge_chunk_ids([], ["x", "y"]) == ["x", "y"]


@pytest.mark.asyncio
async def test_reindex_accumulates_chunk_count(tmp_path):
    fm = FolderManager(state_dir=tmp_path)
    await fm.initialize()

    # First full index: 5 chunks.
    await fm.add_folder(
        folder_path="/repo",
        chunk_count=5,
        chunk_ids=["a", "b", "c", "d", "e"],
        include_code=True,
    )

    # Incremental reindex touches 2 chunks (one overlaps). The call site must
    # pass the UNION count via _merge_chunk_ids, not the per-run delta.
    rec = await fm.get_folder("/repo")
    assert rec is not None
    merged = _merge_chunk_ids(rec.chunk_ids, ["e", "f"])
    await fm.add_folder(
        folder_path="/repo",
        chunk_count=len(merged),
        chunk_ids=merged,
        include_code=True,
    )

    rec = await fm.get_folder("/repo")
    assert rec is not None
    assert rec.chunk_count == 6  # a,b,c,d,e,f — not the 2-chunk delta
