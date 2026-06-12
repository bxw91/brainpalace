"""Unit tests for ChunkEvictionService."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from brainpalace_server.services.chunk_eviction_service import ChunkEvictionService
from brainpalace_server.services.manifest_tracker import (
    FileRecord,
    FolderManifest,
    ManifestTracker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_storage(deleted_count: int = 0) -> AsyncMock:
    """Create a mock StorageBackendProtocol with delete_by_ids."""
    storage = AsyncMock()
    storage.delete_by_ids = AsyncMock(return_value=deleted_count)
    return storage


def make_file_record(
    checksum: str = "abc123",
    mtime: float = 1700000000.0,
    chunk_ids: list[str] | None = None,
) -> FileRecord:
    return FileRecord(
        checksum=checksum,
        mtime=mtime,
        chunk_ids=chunk_ids if chunk_ids is not None else ["chunk-1"],
    )


async def make_tracker_with_manifest(
    tmp_path: Path,
    folder_path: str,
    manifest: FolderManifest,
) -> ManifestTracker:
    tracker = ManifestTracker(manifests_dir=tmp_path / "manifests")
    await tracker.save(manifest)
    return tracker


# ---------------------------------------------------------------------------
# Test: first-time indexing (no manifest exists)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_manifest_treats_all_files_as_added(tmp_path: Path) -> None:
    tracker = ManifestTracker(manifests_dir=tmp_path / "manifests")
    storage = make_mock_storage()
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    current_files = ["/folder/a.py", "/folder/b.py", "/folder/c.md"]
    summary, files_to_index = await service.compute_diff_and_evict(
        folder_path="/folder",
        current_files=current_files,
        force=False,
    )

    assert set(summary.files_added) == set(current_files)
    assert summary.files_changed == []
    assert summary.files_deleted == []
    assert summary.files_unchanged == []
    assert summary.chunks_evicted == 0
    assert summary.chunks_to_create == 3
    assert set(files_to_index) == set(current_files)
    storage.delete_by_ids.assert_not_called()


# ---------------------------------------------------------------------------
# Test: incremental with no changes (all mtime same)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incremental_no_changes_all_unchanged(tmp_path: Path) -> None:
    folder_path = "/project/docs"
    file_a = "/project/docs/a.py"
    file_b = "/project/docs/b.py"

    prior = FolderManifest(
        folder_path=folder_path,
        files={
            file_a: make_file_record(checksum="aaa", mtime=100.0, chunk_ids=["c1"]),
            file_b: make_file_record(checksum="bbb", mtime=200.0, chunk_ids=["c2"]),
        },
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage()
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    current_files = [file_a, file_b]

    # Mock os.stat to return the same mtime as in the manifest
    def fake_stat(fp: str, **kwargs: object) -> os.stat_result:  # type: ignore[override]
        mtime = 100.0 if fp == file_a else 200.0
        # Override st_mtime to be float
        return type("FakeStat", (), {"st_mtime": mtime})()  # type: ignore[return-value]

    with patch(
        "brainpalace_server.services.chunk_eviction_service.os.stat",
        side_effect=fake_stat,
    ):
        summary, files_to_index = await service.compute_diff_and_evict(
            folder_path=folder_path,
            current_files=current_files,
            force=False,
        )

    assert summary.files_added == []
    assert summary.files_changed == []
    assert summary.files_deleted == []
    assert set(summary.files_unchanged) == {file_a, file_b}
    assert summary.chunks_evicted == 0
    assert summary.chunks_to_create == 0
    assert files_to_index == []
    storage.delete_by_ids.assert_not_called()


# ---------------------------------------------------------------------------
# Test: incremental with deleted file — chunks evicted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incremental_deleted_file_chunks_evicted(tmp_path: Path) -> None:
    folder_path = "/project/src"
    file_a = "/project/src/kept.py"
    file_b = "/project/src/deleted.py"

    prior = FolderManifest(
        folder_path=folder_path,
        files={
            file_a: make_file_record(checksum="aaa", mtime=100.0, chunk_ids=["c1"]),
            file_b: make_file_record(
                checksum="bbb", mtime=200.0, chunk_ids=["c2", "c3"]
            ),
        },
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage(deleted_count=2)
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    # file_b is no longer on disk
    current_files = [file_a]

    def fake_stat(fp: str, **kwargs: object) -> object:
        return type("FakeStat", (), {"st_mtime": 100.0})()

    with patch(
        "brainpalace_server.services.chunk_eviction_service.os.stat",
        side_effect=fake_stat,
    ):
        summary, files_to_index = await service.compute_diff_and_evict(
            folder_path=folder_path,
            current_files=current_files,
            force=False,
        )

    assert summary.files_added == []
    assert summary.files_changed == []
    assert summary.files_deleted == [file_b]
    assert summary.files_unchanged == [file_a]
    assert summary.chunks_evicted == 2
    assert summary.chunks_to_create == 0
    assert files_to_index == []

    storage.delete_by_ids.assert_called_once_with(["c2", "c3"])


# ---------------------------------------------------------------------------
# Test: incremental with changed file (different checksum)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incremental_changed_file_old_chunks_evicted(tmp_path: Path) -> None:
    folder_path = "/project"
    file_a = "/project/changed.py"

    prior = FolderManifest(
        folder_path=folder_path,
        files={
            file_a: make_file_record(
                checksum="old-checksum", mtime=100.0, chunk_ids=["old-c1", "old-c2"]
            ),
        },
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage(deleted_count=2)
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    current_files = [file_a]

    def fake_stat(fp: str, **kwargs: object) -> object:
        # mtime changed
        return type("FakeStat", (), {"st_mtime": 999.0})()

    with (
        patch(
            "brainpalace_server.services.chunk_eviction_service.os.stat",
            side_effect=fake_stat,
        ),
        patch(
            "brainpalace_server.services.chunk_eviction_service.compute_file_checksum",
            return_value="new-checksum",
        ),
    ):
        summary, files_to_index = await service.compute_diff_and_evict(
            folder_path=folder_path,
            current_files=current_files,
            force=False,
        )

    assert summary.files_added == []
    assert summary.files_changed == [file_a]
    assert summary.files_deleted == []
    assert summary.files_unchanged == []
    assert summary.chunks_evicted == 2
    assert summary.chunks_to_create == 1
    assert files_to_index == [file_a]

    storage.delete_by_ids.assert_called_once_with(["old-c1", "old-c2"])


@pytest.mark.asyncio
async def test_defer_changed_eviction_holds_changed_evicts_deleted(
    tmp_path: Path,
) -> None:
    """With defer on: changed-file chunks are held (returned), deleted-file
    chunks are evicted immediately."""
    folder_path = "/project"
    changed = "/project/changed.py"
    gone = "/project/gone.py"

    prior = FolderManifest(
        folder_path=folder_path,
        files={
            changed: make_file_record(
                checksum="old", mtime=100.0, chunk_ids=["chg-1", "chg-2"]
            ),
            gone: make_file_record(checksum="g", mtime=100.0, chunk_ids=["gone-1"]),
        },
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage(deleted_count=1)
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    def fake_stat(fp: str, **kwargs: object) -> object:
        return type("FakeStat", (), {"st_mtime": 999.0})()

    with (
        patch(
            "brainpalace_server.services.chunk_eviction_service.os.stat",
            side_effect=fake_stat,
        ),
        patch(
            "brainpalace_server.services.chunk_eviction_service.compute_file_checksum",
            return_value="new",
        ),
    ):
        summary, files_to_index = await service.compute_diff_and_evict(
            folder_path=folder_path,
            current_files=[changed],  # gone.py absent on disk → deleted
            force=False,
            defer_changed_eviction=True,
        )

    assert summary.files_changed == [changed]
    assert summary.files_deleted == [gone]
    # Only the DELETED file's chunk evicted now; changed file's held back.
    storage.delete_by_ids.assert_called_once_with(["gone-1"])
    assert sorted(summary.deferred_evict_ids) == ["chg-1", "chg-2"]
    assert summary.chunks_evicted == 1


@pytest.mark.asyncio
async def test_defer_off_evicts_changed_immediately(tmp_path: Path) -> None:
    """Default (defer off) keeps the old behavior: changed chunks evicted now."""
    folder_path = "/project"
    changed = "/project/changed.py"
    prior = FolderManifest(
        folder_path=folder_path,
        files={
            changed: make_file_record(
                checksum="old", mtime=100.0, chunk_ids=["chg-1", "chg-2"]
            ),
        },
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage(deleted_count=2)
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    def fake_stat(fp: str, **kwargs: object) -> object:
        return type("FakeStat", (), {"st_mtime": 999.0})()

    with (
        patch(
            "brainpalace_server.services.chunk_eviction_service.os.stat",
            side_effect=fake_stat,
        ),
        patch(
            "brainpalace_server.services.chunk_eviction_service.compute_file_checksum",
            return_value="new",
        ),
    ):
        summary, _ = await service.compute_diff_and_evict(
            folder_path=folder_path,
            current_files=[changed],
            force=False,
        )

    storage.delete_by_ids.assert_called_once_with(["chg-1", "chg-2"])
    assert summary.deferred_evict_ids == []


# ---------------------------------------------------------------------------
# Test: force mode — all prior chunks evicted, all files returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_mode_evicts_all_prior_chunks(tmp_path: Path) -> None:
    folder_path = "/force/test"
    file_a = "/force/test/a.py"
    file_b = "/force/test/b.py"

    prior = FolderManifest(
        folder_path=folder_path,
        files={
            file_a: make_file_record(chunk_ids=["c1", "c2"]),
            file_b: make_file_record(chunk_ids=["c3"]),
        },
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage(deleted_count=3)
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    current_files = [file_a, file_b, "/force/test/new.py"]
    summary, files_to_index = await service.compute_diff_and_evict(
        folder_path=folder_path,
        current_files=current_files,
        force=True,
    )

    assert set(summary.files_added) == set(current_files)
    assert summary.files_changed == []
    assert summary.files_deleted == []
    assert summary.files_unchanged == []
    assert summary.chunks_evicted == 3
    assert summary.chunks_to_create == 3
    assert set(files_to_index) == set(current_files)

    # Verify prior chunk IDs were evicted (order may vary)
    call_args = storage.delete_by_ids.call_args[0][0]
    assert set(call_args) == {"c1", "c2", "c3"}

    # Verify manifest was deleted
    manifest_file = tracker._manifest_path(folder_path)
    assert not manifest_file.exists()


@pytest.mark.asyncio
async def test_force_mode_with_no_prior_manifest(tmp_path: Path) -> None:
    folder_path = "/no/prior"
    tracker = ManifestTracker(manifests_dir=tmp_path / "manifests")
    storage = make_mock_storage()
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    current_files = ["/no/prior/a.py"]
    summary, files_to_index = await service.compute_diff_and_evict(
        folder_path=folder_path,
        current_files=current_files,
        force=True,
    )

    assert summary.chunks_evicted == 0
    assert set(files_to_index) == set(current_files)
    storage.delete_by_ids.assert_not_called()


# ---------------------------------------------------------------------------
# Test: mtime changed but checksum same — file counted as unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mtime_changed_same_checksum_counted_as_unchanged(tmp_path: Path) -> None:
    folder_path = "/stable"
    file_a = "/stable/a.py"
    stable_checksum = "stable-sha256"

    prior = FolderManifest(
        folder_path=folder_path,
        files={
            file_a: make_file_record(
                checksum=stable_checksum, mtime=100.0, chunk_ids=["c1"]
            ),
        },
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage()
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    def fake_stat(fp: str, **kwargs: object) -> object:
        # mtime changed
        return type("FakeStat", (), {"st_mtime": 999.0})()

    with (
        patch(
            "brainpalace_server.services.chunk_eviction_service.os.stat",
            side_effect=fake_stat,
        ),
        patch(
            "brainpalace_server.services.chunk_eviction_service.compute_file_checksum",
            return_value=stable_checksum,  # same checksum
        ),
    ):
        summary, files_to_index = await service.compute_diff_and_evict(
            folder_path=folder_path,
            current_files=[file_a],
            force=False,
        )

    assert summary.files_unchanged == [file_a]
    assert summary.files_changed == []
    assert summary.chunks_evicted == 0
    assert files_to_index == []
    storage.delete_by_ids.assert_not_called()


# ---------------------------------------------------------------------------
# Test: mixed scenario — added + changed + deleted + unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_diff_scenario(tmp_path: Path) -> None:
    folder_path = "/mixed"
    file_unchanged = "/mixed/unchanged.py"
    file_changed = "/mixed/changed.py"
    file_deleted = "/mixed/deleted.py"
    file_new = "/mixed/new.py"

    prior = FolderManifest(
        folder_path=folder_path,
        files={
            file_unchanged: make_file_record(
                checksum="unch", mtime=1.0, chunk_ids=["uc1"]
            ),
            file_changed: make_file_record(
                checksum="old", mtime=2.0, chunk_ids=["cc1", "cc2"]
            ),
            file_deleted: make_file_record(
                checksum="del", mtime=3.0, chunk_ids=["dc1"]
            ),
        },
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage(deleted_count=3)
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    current_files = [file_unchanged, file_changed, file_new]

    def fake_stat(fp: str, **kwargs: object) -> object:
        if fp == file_unchanged:
            return type("FakeStat", (), {"st_mtime": 1.0})()  # mtime unchanged
        return type("FakeStat", (), {"st_mtime": 999.0})()  # mtime changed

    with (
        patch(
            "brainpalace_server.services.chunk_eviction_service.os.stat",
            side_effect=fake_stat,
        ),
        patch(
            "brainpalace_server.services.chunk_eviction_service.compute_file_checksum",
            return_value="new-checksum",  # different from "old"
        ),
    ):
        summary, files_to_index = await service.compute_diff_and_evict(
            folder_path=folder_path,
            current_files=current_files,
            force=False,
        )

    assert summary.files_added == [file_new]
    assert summary.files_changed == [file_changed]
    assert summary.files_deleted == [file_deleted]
    assert summary.files_unchanged == [file_unchanged]
    assert summary.chunks_evicted == 3
    assert summary.chunks_to_create == 2  # new + changed
    assert set(files_to_index) == {file_new, file_changed}

    # Verify both changed and deleted chunks were evicted
    evicted_ids = set(storage.delete_by_ids.call_args[0][0])
    assert evicted_ids == {"cc1", "cc2", "dc1"}


# ---------------------------------------------------------------------------
# Test: empty current_files — all prior files treated as deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_files_deleted(tmp_path: Path) -> None:
    folder_path = "/gone"
    file_a = "/gone/a.py"

    prior = FolderManifest(
        folder_path=folder_path,
        files={file_a: make_file_record(chunk_ids=["c1"])},
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage(deleted_count=1)
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    summary, files_to_index = await service.compute_diff_and_evict(
        folder_path=folder_path,
        current_files=[],
        force=False,
    )

    assert summary.files_deleted == [file_a]
    assert summary.chunks_evicted == 1
    assert files_to_index == []
    storage.delete_by_ids.assert_called_once_with(["c1"])


# ---------------------------------------------------------------------------
# Test: no chunks to evict — delete_by_ids not called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_eviction_needed_delete_not_called(tmp_path: Path) -> None:
    folder_path = "/clean"
    file_a = "/clean/a.py"

    prior = FolderManifest(
        folder_path=folder_path,
        files={file_a: make_file_record(mtime=1.0, chunk_ids=["c1"])},
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage()
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)

    def fake_stat(fp: str, **kwargs: object) -> object:
        return type("FakeStat", (), {"st_mtime": 1.0})()

    with patch(
        "brainpalace_server.services.chunk_eviction_service.os.stat",
        side_effect=fake_stat,
    ):
        summary, files_to_index = await service.compute_diff_and_evict(
            folder_path=folder_path,
            current_files=[file_a],
            force=False,
        )

    assert summary.chunks_evicted == 0
    storage.delete_by_ids.assert_not_called()


# ---------------------------------------------------------------------------
# Phase L: large-file re-embed cooldown throttle
# ---------------------------------------------------------------------------

from brainpalace_server.config.indexing_config import IndexingConfig  # noqa: E402

NOW = 1_700_000_000.0


def _throttle_cfg(**kw: object) -> IndexingConfig:
    base = {
        "reembed_cooldown_seconds": 3600,
        "big_file_chunks": 200,
        "max_file_bytes_throttle": 262144,
        "skip_minified": True,
    }
    base.update(kw)
    return IndexingConfig(**base)  # type: ignore[arg-type]


def _changed_stat(size: int):
    def fake_stat(fp: str, **kwargs: object) -> object:
        return type("FakeStat", (), {"st_mtime": 999.0, "st_size": size})()

    return fake_stat


async def _run_changed(
    tmp_path: Path,
    *,
    prior_chunks: list[str],
    last_embedded_at: float,
    size: int,
    cfg: IndexingConfig,
):
    folder_path = "/proj"
    fp = "/proj/bundle.js"
    prior = FolderManifest(
        folder_path=folder_path,
        files={
            fp: FileRecord(
                checksum="old",
                mtime=100.0,
                chunk_ids=prior_chunks,
                last_embedded_at=last_embedded_at,
                size_bytes=size,
            )
        },
    )
    tracker = await make_tracker_with_manifest(tmp_path, folder_path, prior)
    storage = make_mock_storage(deleted_count=len(prior_chunks))
    service = ChunkEvictionService(manifest_tracker=tracker, storage_backend=storage)
    with (
        patch(
            "brainpalace_server.services.chunk_eviction_service.os.stat",
            side_effect=_changed_stat(size),
        ),
        patch(
            "brainpalace_server.services.chunk_eviction_service.compute_file_checksum",
            return_value="new-checksum",
        ),
        patch(
            "brainpalace_server.services.chunk_eviction_service.time.time",
            return_value=NOW,
        ),
    ):
        summary, files_to_index = await service.compute_diff_and_evict(
            folder_path=folder_path,
            current_files=[fp],
            force=False,
            indexing_config=cfg,
        )
    return summary, files_to_index, storage, fp


@pytest.mark.asyncio
async def test_large_changed_file_within_cooldown_is_deferred(tmp_path: Path) -> None:
    big_chunks = [f"c{i}" for i in range(250)]  # >= 200 → large
    summary, files_to_index, storage, fp = await _run_changed(
        tmp_path,
        prior_chunks=big_chunks,
        last_embedded_at=NOW - 10,  # within 3600s cooldown
        size=1000,
        cfg=_throttle_cfg(),
    )
    assert summary.files_deferred == [fp]
    assert summary.files_changed == []
    assert files_to_index == []
    assert summary.chunks_evicted == 0
    storage.delete_by_ids.assert_not_called()


@pytest.mark.asyncio
async def test_large_changed_file_after_cooldown_reembeds(tmp_path: Path) -> None:
    big_chunks = [f"c{i}" for i in range(250)]
    summary, files_to_index, storage, fp = await _run_changed(
        tmp_path,
        prior_chunks=big_chunks,
        last_embedded_at=NOW - 7200,  # older than cooldown
        size=1000,
        cfg=_throttle_cfg(),
    )
    assert summary.files_deferred == []
    assert summary.files_changed == [fp]
    assert files_to_index == [fp]


@pytest.mark.asyncio
async def test_small_changed_file_never_throttled(tmp_path: Path) -> None:
    summary, files_to_index, storage, fp = await _run_changed(
        tmp_path,
        prior_chunks=["c1", "c2"],  # tiny, < 200
        last_embedded_at=NOW - 10,  # within cooldown but small
        size=1000,  # < 256 KB
        cfg=_throttle_cfg(),
    )
    assert summary.files_deferred == []
    assert summary.files_changed == [fp]


@pytest.mark.asyncio
async def test_large_by_bytes_within_cooldown_is_deferred(tmp_path: Path) -> None:
    summary, files_to_index, storage, fp = await _run_changed(
        tmp_path,
        prior_chunks=["c1"],  # small chunk count
        last_embedded_at=NOW - 10,
        size=300_000,  # >= 256 KB → large by bytes
        cfg=_throttle_cfg(),
    )
    assert summary.files_deferred == [fp]
    assert files_to_index == []


@pytest.mark.asyncio
async def test_first_index_of_large_file_embeds(tmp_path: Path) -> None:
    big_chunks = [f"c{i}" for i in range(250)]
    summary, files_to_index, storage, fp = await _run_changed(
        tmp_path,
        prior_chunks=big_chunks,
        last_embedded_at=0.0,  # never recorded (legacy/first)
        size=1000,
        cfg=_throttle_cfg(),
    )
    assert summary.files_deferred == []
    assert summary.files_changed == [fp]


@pytest.mark.asyncio
async def test_cooldown_zero_disables_throttle(tmp_path: Path) -> None:
    big_chunks = [f"c{i}" for i in range(250)]
    summary, files_to_index, storage, fp = await _run_changed(
        tmp_path,
        prior_chunks=big_chunks,
        last_embedded_at=NOW - 10,
        size=1000,
        cfg=_throttle_cfg(reembed_cooldown_seconds=0),
    )
    assert summary.files_deferred == []
    assert summary.files_changed == [fp]
