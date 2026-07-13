import pytest

from brainpalace_server.services.folder_manager import FolderManager


@pytest.mark.asyncio
async def test_initialize_prune_false_keeps_missing_records(tmp_path):
    fm = FolderManager(state_dir=tmp_path)
    await fm.add_folder("/gone/from/disk", chunk_count=1, chunk_ids=["a_0"])

    fm2 = FolderManager(state_dir=tmp_path)
    await fm2.initialize(prune=False)  # missing path must NOT be pruned
    paths = {r.folder_path for r in await fm2.list_folders()}
    assert "/gone/from/disk" in paths


@pytest.mark.asyncio
async def test_initialize_default_prunes_missing(tmp_path):
    fm = FolderManager(state_dir=tmp_path)
    await fm.add_folder("/gone/from/disk", chunk_count=1, chunk_ids=["a_0"])

    fm2 = FolderManager(state_dir=tmp_path)
    await fm2.initialize()  # default prunes the missing path
    paths = {r.folder_path for r in await fm2.list_folders()}
    assert "/gone/from/disk" not in paths
