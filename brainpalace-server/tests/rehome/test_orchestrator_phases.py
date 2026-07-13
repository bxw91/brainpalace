import pytest
import yaml

from brainpalace_server.rehome import orchestrator as orch
from brainpalace_server.rehome.state import new_rehome_state
from brainpalace_server.services.folder_manager import FolderManager
from brainpalace_server.storage.vector_store import VectorStoreManager


@pytest.mark.asyncio
async def test_vector_phase_swaps_all_metadata_and_checkpoints(tmp_path):
    mgr = VectorStoreManager(
        persist_dir=str(tmp_path / "chroma"), collection_name="tcol"
    )
    await mgr.initialize()
    await mgr.upsert_documents(
        ids=[f"c{i}" for i in range(3)],
        embeddings=[[0.1, 0.2]] * 3,
        documents=["a", "b", "c"],
        metadatas=[
            {"source": f"/old/root/f{i}.py", "file_path": f"/old/root/f{i}.py"}
            for i in range(3)
        ],
    )
    st = new_rehome_state("u", "/old/root", "/new/home")
    ctx = orch.RehomeContext(
        state_dir=tmp_path,
        old_root="/old/root",
        new_root="/new/home",
        state=st,
        vector=mgr,
        bm25=None,
        graph=None,
        refcat=None,
        folders=None,
        jobs=None,
    )
    await orch._run_phase(5, ctx)  # vector metadata phase

    for i in range(3):
        row = await mgr.get_by_id(f"c{i}")
        assert row["metadata"]["source"] == f"/new/home/f{i}.py"
        assert row["metadata"]["file_path"] == f"/new/home/f{i}.py"
    # embeddings preserved (no re-embed): count unchanged, vectors intact
    assert await mgr.get_count() == 3


@pytest.mark.asyncio
async def test_vector_phase_resumes_from_cursor_without_double_swap(tmp_path):
    mgr = VectorStoreManager(
        persist_dir=str(tmp_path / "chroma"), collection_name="tcol"
    )
    await mgr.initialize()
    ids = ["c1", "c2", "c3", "c4"]
    # c1/c2 already swapped by a prior (crashed) run; c3/c4 still under old_root.
    metadatas = [
        {"source": "/new/home/c1.py"},
        {"source": "/new/home/c2.py"},
        {"source": "/old/root/c3.py"},
        {"source": "/old/root/c4.py"},
    ]
    await mgr.upsert_documents(
        ids=ids,
        embeddings=[[0.1, 0.2]] * 4,
        documents=["a", "b", "c", "d"],
        metadatas=metadatas,
    )
    st = new_rehome_state("u", "/old/root", "/new/home")
    st.cursor = "c2"  # first batch (c1, c2) already swapped in a prior crash
    ctx = orch.RehomeContext(
        state_dir=tmp_path,
        old_root="/old/root",
        new_root="/new/home",
        state=st,
        vector=mgr,
        bm25=None,
        graph=None,
        refcat=None,
        folders=None,
        jobs=None,
    )
    await orch._run_phase(5, ctx)

    for cid in ids:
        row = await mgr.get_by_id(cid)
        assert row["metadata"]["source"] == f"/new/home/{cid}.py"
    assert st.cursor is None  # cleared on completion


@pytest.mark.asyncio
async def test_folder_records_phase_rekeys(tmp_path):
    fm = FolderManager(tmp_path)
    await fm.add_folder("/old/root/pkg", chunk_count=1, chunk_ids=["a_0"])
    st = new_rehome_state("u", "/old/root", "/new/home")
    ctx = orch.RehomeContext(
        state_dir=tmp_path,
        old_root="/old/root",
        new_root="/new/home",
        state=st,
        vector=None,
        bm25=None,
        graph=None,
        refcat=None,
        folders=fm,
        jobs=None,
    )
    await orch._run_phase(2, ctx)
    paths = {r.folder_path for r in await fm.list_folders()}
    assert "/new/home/pkg" in paths


@pytest.mark.asyncio
async def test_config_excludes_phase_swaps(tmp_path):
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump({"indexing": {"exclude_patterns": ["/old/root/build"]}})
    )
    st = new_rehome_state("u", "/old/root", "/new/home")
    ctx = orch.RehomeContext(
        state_dir=tmp_path,
        old_root="/old/root",
        new_root="/new/home",
        state=st,
        vector=None,
        bm25=None,
        graph=None,
        refcat=None,
        folders=None,
        jobs=None,
    )

    await orch._run_phase(1, ctx)
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert data["indexing"]["exclude_patterns"] == ["/new/home/build"]
