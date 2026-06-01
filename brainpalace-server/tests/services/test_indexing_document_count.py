"""Phase 3 — /status total_documents derives from persisted manifests.

``total_documents`` used to come from the in-process ``IndexingService._state``,
which is only set when a full index runs in *this* process. Async index jobs
run in the worker, so the API process reported 0 while the store held chunks.
``get_document_count`` derives the count from the persisted folder manifests
(distinct indexed file paths), falling back to the in-process state only when
manifests are unavailable.
"""

from types import SimpleNamespace

import pytest

from brainpalace_server.services.folder_manager import FolderManager
from brainpalace_server.services.indexing_service import IndexingService
from brainpalace_server.services.manifest_tracker import (
    FileRecord,
    FolderManifest,
    ManifestTracker,
)


def _service(folder_manager, manifest_tracker, state_total=0) -> IndexingService:
    svc = IndexingService.__new__(IndexingService)
    svc.folder_manager = folder_manager
    svc.manifest_tracker = manifest_tracker
    svc._state = SimpleNamespace(total_documents=state_total)
    return svc


@pytest.mark.asyncio
async def test_get_document_count_counts_distinct_files(tmp_path):
    fm = FolderManager(state_dir=tmp_path / "fm")
    await fm.initialize()
    mt = ManifestTracker(manifests_dir=tmp_path / "manifests")

    await fm.add_folder(folder_path="/repo", chunk_count=5, chunk_ids=["a", "b", "c"])
    manifest = FolderManifest(folder_path="/repo")
    # 3 files, one multi-chunk -> 3 documents, not 5 chunks.
    manifest.files["/repo/a.py"] = FileRecord("h1", 1.0, ["a0", "a1"])
    manifest.files["/repo/b.py"] = FileRecord("h2", 1.0, ["b0"])
    manifest.files["/repo/c.py"] = FileRecord("h3", 1.0, ["c0", "c1"])
    await mt.save(manifest)

    svc = _service(fm, mt, state_total=0)  # state stale
    assert await svc.get_document_count() == 3


@pytest.mark.asyncio
async def test_get_document_count_unions_files_across_folders(tmp_path):
    fm = FolderManager(state_dir=tmp_path / "fm")
    await fm.initialize()
    mt = ManifestTracker(manifests_dir=tmp_path / "manifests")

    for folder, files in (("/r1", ["x.py", "y.py"]), ("/r2", ["z.py"])):
        await fm.add_folder(folder_path=folder, chunk_count=1, chunk_ids=["c"])
        m = FolderManifest(folder_path=folder)
        for f in files:
            m.files[f"{folder}/{f}"] = FileRecord("h", 1.0, ["c"])
        await mt.save(m)

    svc = _service(fm, mt, state_total=0)
    assert await svc.get_document_count() == 3


@pytest.mark.asyncio
async def test_get_document_count_falls_back_without_trackers():
    svc = _service(None, None, state_total=7)
    assert await svc.get_document_count() == 7
