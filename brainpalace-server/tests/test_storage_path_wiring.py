"""Tests for storage-path wiring — indexes must live under .brainpalace/data/.

Phase I: regression guard for the CWD-relative chroma_db / bm25_index bug.
"""

from __future__ import annotations

import brainpalace_server.indexing.bm25_index as bm25_mod
import brainpalace_server.storage.vector_store as vs_mod
from brainpalace_server.indexing.bm25_index import (
    BM25IndexManager,
    get_bm25_manager,
    set_bm25_manager,
)
from brainpalace_server.storage.vector_store import (
    VectorStoreManager,
    get_vector_store,
    set_vector_store,
)


def test_set_vector_store_replaces_global_singleton() -> None:
    """set_vector_store() makes get_vector_store() return the given instance."""
    original = vs_mod._vector_store
    try:
        custom = VectorStoreManager(persist_dir="/tmp/abi-test/chroma_db")
        set_vector_store(custom)
        assert get_vector_store() is custom
        assert get_vector_store().persist_dir == "/tmp/abi-test/chroma_db"
    finally:
        vs_mod._vector_store = original


def test_set_bm25_manager_replaces_global_singleton() -> None:
    """set_bm25_manager() makes get_bm25_manager() return the given instance."""
    original = bm25_mod._bm25_manager
    try:
        custom = BM25IndexManager(persist_dir="/tmp/abi-test/bm25_index")
        set_bm25_manager(custom)
        assert get_bm25_manager() is custom
        assert get_bm25_manager().persist_dir == "/tmp/abi-test/bm25_index"
    finally:
        bm25_mod._bm25_manager = original


def test_chroma_backend_reuses_registered_singletons() -> None:
    """ChromaBackend() with no args reuses set_*-registered managers.

    Core Phase I guarantee: when the lifespan registers project-resolved
    managers, a subsequently-constructed ChromaBackend inherits their
    persist dirs instead of building CWD-relative ones.
    """
    from brainpalace_server.storage.chroma.backend import ChromaBackend

    vs_original = vs_mod._vector_store
    bm_original = bm25_mod._bm25_manager
    try:
        vs = VectorStoreManager(persist_dir="/tmp/abi-test/.brainpalace/data/chroma_db")
        bm = BM25IndexManager(persist_dir="/tmp/abi-test/.brainpalace/data/bm25_index")
        set_vector_store(vs)
        set_bm25_manager(bm)

        backend = ChromaBackend()  # no args — must fall back to singletons

        assert backend.vector_store is vs
        assert backend.bm25_manager is bm
        assert ".brainpalace/data/chroma_db" in backend.vector_store.persist_dir
        assert ".brainpalace/data/bm25_index" in backend.bm25_manager.persist_dir
    finally:
        vs_mod._vector_store = vs_original
        bm25_mod._bm25_manager = bm_original
