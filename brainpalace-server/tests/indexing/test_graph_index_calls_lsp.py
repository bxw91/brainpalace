import pytest

from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.graph_store import GraphStoreManager


class _Doc:
    def __init__(self, text, metadata):
        self.text = text
        self.metadata = metadata

    def get_content(self):
        return self.text


def _pyfile(path, src):
    return _Doc(
        src,
        {
            "source_type": "code",
            "language": "python",
            "file_path": path,
            "source": path,
        },
    )


@pytest.fixture
def gi(tmp_path):
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    return GraphIndexManager(graph_store=mgr), mgr


def _edges(mgr, label):
    return {
        (r[0], r[1])
        for r in mgr._graph_store._conn.execute(
            "SELECT source_id, target_id FROM edges"
            " WHERE label = ? AND valid_until IS NULL",
            (label,),
        )
    }


def test_ast_intrafile_calls_persisted(gi):
    index, mgr = gi
    src = "def helper():\n    pass\ndef top():\n    helper()\n"
    index.build_from_documents([_pyfile("m.py", src)])
    assert ("m.py:top", "m.py:helper") in _edges(mgr, "calls")


def test_lsp_calls_merge_when_enabled(gi, monkeypatch):
    index, mgr = gi
    from brainpalace_server.lsp import servers

    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: lang == "python")

    class _FakeLsp:
        def extract_from_symbols(self, symbols, source_chunk_id=None):
            from brainpalace_server.models.graph import GraphTriple

            return [
                GraphTriple(
                    subject="top",
                    predicate="calls",
                    object="ext",
                    subject_id="m.py:top",
                    object_id="other.py:ext",
                    subject_name="top",
                    object_name="ext",
                    subject_type="Function",
                    object_type="Function",
                )
            ]

    monkeypatch.setattr(index, "_get_lsp_extractor", lambda root=None: _FakeLsp())
    src = "def top():\n    pass\n"
    index.build_from_documents([_pyfile("m.py", src)])
    assert ("m.py:top", "other.py:ext") in _edges(mgr, "calls")

    # The LSP edge was written with forced source_file="m.py", so re-indexing
    # that file invalidates it. Disable LSP for the second build and assert the
    # stale cross-file edge is gone (proves §3 purge owns LSP triplets too).
    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: False)
    index.build_from_documents([_pyfile("m.py", "def renamed():\n    pass\n")])
    assert ("m.py:top", "other.py:ext") not in _edges(mgr, "calls")


def test_lsp_skipped_when_disabled(gi, monkeypatch):
    index, mgr = gi
    from brainpalace_server.lsp import servers

    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: False)
    called = {"n": 0}

    class _Boom:
        def extract_from_symbols(self, *a, **k):
            called["n"] += 1
            return []

    monkeypatch.setattr(index, "_get_lsp_extractor", lambda root=None: _Boom())
    index.build_from_documents([_pyfile("m.py", "def a():\n    pass\n")])
    assert called["n"] == 0  # gate short-circuits before building the extractor
