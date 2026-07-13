import pytest

from brainpalace_server.storage.vector_store import VectorStoreManager


@pytest.mark.asyncio
async def test_get_all_ids_sorted_and_metadatas_paired(tmp_path):
    mgr = VectorStoreManager(persist_dir=str(tmp_path), collection_name="tcol")
    await mgr.initialize()
    await mgr.upsert_documents(
        ids=["c2", "c1", "c3"],
        embeddings=[[0.1, 0.2]] * 3,
        documents=["a", "b", "c"],
        metadatas=[
            {"source": "/old/2"},
            {"source": "/old/1"},
            {"source": "/old/3"},
        ],
    )
    assert await mgr.get_all_ids() == ["c1", "c2", "c3"]  # stable sort
    mds = await mgr.get_metadatas(["c1", "c3"])
    assert mds[0]["source"] == "/old/1"
    assert mds[1]["source"] == "/old/3"


@pytest.mark.asyncio
async def test_get_metadatas_missing_id_is_empty(tmp_path):
    mgr = VectorStoreManager(persist_dir=str(tmp_path), collection_name="tcol")
    await mgr.initialize()
    await mgr.upsert_documents(
        ids=["c1"],
        embeddings=[[1.0, 0.0]],
        documents=["x"],
        metadatas=[{"source": "/old/1"}],
    )
    assert await mgr.get_metadatas(["nope"]) == [{}]
