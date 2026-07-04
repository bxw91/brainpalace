# brainpalace-server/tests/indexing/test_graph_index_lsp_close.py
"""Plan 5 Task 4 — server processes must not outlive the build."""

from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.lsp import servers
from brainpalace_server.storage.graph_store import GraphStoreManager


class _Doc:
    def __init__(self, text, metadata):
        self.text = text
        self.metadata = metadata

    def get_content(self):
        return self.text


def test_lsp_extractor_closed_after_build(tmp_path, monkeypatch):
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    index = GraphIndexManager(graph_store=mgr)
    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: lang == "python")

    closed = {"n": 0}

    class _FakeLsp:
        def extract_from_symbols(self, symbols, source_chunk_id=None):
            return []

        def extract_references(self, sites, source_chunk_id=None):
            return []

        def close(self):
            closed["n"] += 1

    monkeypatch.setattr(index, "_get_lsp_extractor", lambda root=None: _FakeLsp())
    index._lsp_extractor = _FakeLsp()  # simulate a built extractor
    index.build_from_documents(
        [
            _Doc(
                "def a():\n    pass\n",
                {
                    "source_type": "code",
                    "language": "python",
                    "file_path": "m.py",
                    "source": "m.py",
                },
            )
        ]
    )
    assert closed["n"] >= 1
