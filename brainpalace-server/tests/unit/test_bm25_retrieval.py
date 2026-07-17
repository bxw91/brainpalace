"""Unit tests for BM25 retrieval functionality."""

import asyncio

from llama_index.core.schema import TextNode

from brainpalace_server.indexing.bm25_index import BM25IndexManager


class TestBM25IndexManager:
    """Tests for BM25IndexManager."""

    def test_initialize_empty(self, tmp_path):
        """Test initialization with no existing index."""
        manager = BM25IndexManager(persist_dir=str(tmp_path))
        manager.initialize()
        assert manager.is_initialized is False

    def test_build_and_persist(self, tmp_path):
        """Test building and persisting the index."""
        manager = BM25IndexManager(persist_dir=str(tmp_path))
        nodes = [
            TextNode(text="Python is a programming language", id_="node1"),
            TextNode(text="FastAPI is a web framework", id_="node2"),
        ]
        manager.build_index(nodes)
        assert manager.is_initialized is True
        assert (tmp_path / "params.index.json").exists()

    def test_load_existing(self, tmp_path):
        """Test loading an existing index from disk."""
        # First build it
        manager1 = BM25IndexManager(persist_dir=str(tmp_path))
        nodes = [TextNode(text="Sample text for indexing", id_="node1")]
        manager1.build_index(nodes)

        # Then load it with a new manager
        manager2 = BM25IndexManager(persist_dir=str(tmp_path))
        manager2.initialize()
        assert manager2.is_initialized is True
        assert manager2.corpus_size == 1

    def test_reset(self, tmp_path):
        """Test resetting the index."""
        manager = BM25IndexManager(persist_dir=str(tmp_path))
        nodes = [TextNode(text="Sample text for indexing", id_="node1")]
        manager.build_index(nodes)
        assert (tmp_path / "params.index.json").exists()

        manager.reset()
        assert manager.is_initialized is False
        assert not (tmp_path / "params.index.json").exists()

    def test_search_returns_results(self, tmp_path):
        """Test that search_with_filters returns results for a matching query."""
        manager = BM25IndexManager(persist_dir=str(tmp_path))
        nodes = [
            TextNode(text="Python is a programming language", id_="node1"),
            TextNode(text="FastAPI is a web framework", id_="node2"),
        ]
        manager.build_index(nodes)
        results = asyncio.run(
            manager.search_with_filters("python programming", top_k=2)
        )
        assert len(results) > 0
        assert results[0].node.node_id == "node1"

    def test_file_paths_scopes_exactly_below_repo_wide_topk(self, tmp_path):
        """A17 regression: file_paths must scope EXACTLY, not merely over-fetch.

        top_k=1 means the unscoped internal retrieval window is k=top_k*3=3.
        Five decoy nodes outscore the target on the shared term "widget" (more
        occurrences => higher BM25 score), pushing the target's repo-wide rank
        to 6th - below that window. A search scoped to the target's file_path
        must still find it, proving the scope is exact (whole-corpus retrieval
        when file_paths is set), not merely an over-fetch that happens to reach
        far enough.
        """
        manager = BM25IndexManager(persist_dir=str(tmp_path))
        nodes = [
            TextNode(
                text=f"widget widget widget decoy file number {i}",
                id_=f"decoy{i}",
                metadata={"file_path": f"/repo/decoys/decoy{i}.py"},
            )
            for i in range(5)
        ]
        target = TextNode(
            text="widget appears exactly once here",
            id_="target",
            metadata={"file_path": "/repo/brainpalace-dashboard/Usage.tsx"},
        )
        manager.build_index([*nodes, target])

        # Sanity check: unscoped, the target does NOT make the repo-wide
        # top_k*3=3 window (decoys score higher via term frequency).
        unscoped = asyncio.run(manager.search_with_filters("widget", top_k=1))
        assert all(r.node.node_id != "target" for r in unscoped)

        # Scoped: file_paths must recover it anyway.
        scoped = asyncio.run(
            manager.search_with_filters(
                "widget",
                top_k=1,
                file_paths=["*brainpalace-dashboard*"],
            )
        )
        assert len(scoped) == 1
        assert scoped[0].node.node_id == "target"
