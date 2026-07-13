# tests/storage/test_update_metadata_chroma.py
import pytest

from brainpalace_server.storage.vector_store import VectorStoreManager


@pytest.mark.asyncio
async def test_update_metadata_changes_metadata_preserves_embedding(tmp_path):
    mgr = VectorStoreManager(persist_dir=str(tmp_path), collection_name="tcol")
    await mgr.initialize()

    cid = "chunk-1"
    emb = [0.1, 0.2, 0.3]
    await mgr.upsert_documents(
        ids=[cid],
        embeddings=[emb],
        documents=["hello world"],
        metadatas=[{"source": "/old/root/a.py", "language": "python"}],
    )

    before = mgr._collection.get(ids=[cid], include=["embeddings", "metadatas"])
    emb_before = list(before["embeddings"][0])

    await mgr.update_metadata(
        ids=[cid],
        metadatas=[{"source": "/new/home/a.py", "language": "python"}],
    )

    after = mgr._collection.get(ids=[cid], include=["embeddings", "metadatas"])
    assert after["metadatas"][0]["source"] == "/new/home/a.py"
    assert list(after["embeddings"][0]) == emb_before  # embedding untouched


@pytest.mark.asyncio
async def test_update_metadata_idempotent(tmp_path):
    mgr = VectorStoreManager(persist_dir=str(tmp_path), collection_name="tcol")
    await mgr.initialize()
    cid = "c"
    await mgr.upsert_documents(
        ids=[cid],
        embeddings=[[1.0, 0.0]],
        documents=["x"],
        metadatas=[{"source": "/old/a"}],
    )
    md = [{"source": "/new/a"}]
    await mgr.update_metadata(ids=[cid], metadatas=md)
    await mgr.update_metadata(ids=[cid], metadatas=md)  # second apply = no-op
    got = mgr._collection.get(ids=[cid], include=["metadatas"])
    assert got["metadatas"][0]["source"] == "/new/a"
