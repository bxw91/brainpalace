"""Plan 4 Task 2 — add_triplet must work on the llama-index simple backend."""

from brainpalace_server.storage.graph_store import GraphStoreManager


def test_add_triplet_and_persist_on_simple_backend(tmp_path):
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="simple")
    mgr.initialize()
    assert (
        mgr.add_triplet(
            subject="FastAPI",
            predicate="uses",
            obj="Pydantic",
            subject_type="Framework",
            object_type="Library",
        )
        is True
    )
    assert mgr.relationship_count >= 1
    mgr.persist()  # pydantic serialisation path — must not raise
