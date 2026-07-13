import pytest

from brainpalace_server.rehome.swap import rehome_folder_record
from brainpalace_server.services.folder_manager import FolderManager


@pytest.mark.asyncio
async def test_folder_rehome_rekeys_cache_and_persists(tmp_path):
    fm = FolderManager(tmp_path)
    await fm.add_folder("/old/root/pkg", chunk_count=1, chunk_ids=["a_0"])
    await fm.add_folder("/somewhere/else/docs", chunk_count=1, chunk_ids=["b_0"])

    n = await fm.rehome(lambda r: rehome_folder_record(r, "/old/root", "/new/home"))
    assert n == 1

    # a fresh manager loads the persisted, swapped record (rehome must not prune
    # the now-missing /new/home path)
    fm2 = FolderManager(tmp_path)
    await fm2.rehome(lambda r: r)  # load w/o prune, no-op swap
    paths = {r.folder_path for r in await fm2.list_folders()}
    assert "/new/home/pkg" in paths
    assert "/somewhere/else/docs" in paths
