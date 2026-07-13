# tests/storage/test_update_metadata_postgres.py
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("BRAINPALACE_TEST_POSTGRES_DSN"),
    reason="requires a live postgres (set BRAINPALACE_TEST_POSTGRES_DSN)",
)


@pytest.mark.asyncio
async def test_postgres_update_metadata_preserves_embedding():
    from brainpalace_server.storage.postgres.backend import PostgresBackend
    from brainpalace_server.storage.postgres.config import PostgresConfig

    backend = PostgresBackend(
        PostgresConfig.from_database_url(os.environ["BRAINPALACE_TEST_POSTGRES_DSN"])
    )
    await backend.initialize()

    cid = "pg-chunk-1"
    emb = [0.1] * backend.connection_manager.config.dimensions
    await backend.upsert_documents(
        ids=[cid],
        embeddings=[emb],
        documents=["hello"],
        metadatas=[{"source": "/old/root/a.py"}],
    )
    await backend.update_metadata(ids=[cid], metadatas=[{"source": "/new/home/a.py"}])

    row = await backend.get_by_id(cid)
    assert row["metadata"]["source"] == "/new/home/a.py"
    assert row["embedding"] is not None  # embedding still present
