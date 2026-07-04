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


def _manifest(path, src):
    return _Doc(
        src,
        {"source_type": "doc", "file_path": path, "source": path},
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
            "SELECT source_id, target_id FROM edges "
            "WHERE label = ? AND valid_until IS NULL",
            (label,),
        )
    }


def _labels(mgr):
    return {
        r[0]: r[1]
        for r in mgr._graph_store._conn.execute("SELECT id, label FROM nodes")
    }


def test_file_folder_chain_persisted(gi, tmp_path):
    index, mgr = gi
    root = str(tmp_path).replace("\\", "/")
    fp = f"{root}/pkg/sub/m.py"
    index.build_from_documents([_pyfile(fp, "def f():\n    pass\n")], root=root)
    contains = _edges(mgr, "contains")
    assert (f"{root}/pkg", f"{root}/pkg/sub") in contains
    assert (f"{root}/pkg/sub", fp) in contains
    labels = _labels(mgr)
    assert labels[fp] == "File"
    assert labels[f"{root}/pkg/sub"] == "Folder"


def test_imports_resolve_to_repo_file(gi, tmp_path):
    index, mgr = gi
    root = str(tmp_path).replace("\\", "/")
    util = tmp_path / "pkg" / "util.py"
    util.parent.mkdir(parents=True)
    util.write_text("def helper():\n    pass\n")
    util_fp = str(util).replace("\\", "/")
    main_fp = f"{root}/main.py"
    (tmp_path / "main.py").write_text("import pkg.util\nimport os\n")
    index.build_from_documents(
        [_pyfile(main_fp, "import pkg.util\nimport os\n")], root=root
    )
    imports = _edges(mgr, "imports")
    assert (main_fp, util_fp) in imports  # repo hit → File imports File
    assert (main_fp, "os") in imports  # external → Module
    labels = _labels(mgr)
    assert labels[util_fp] == "File"
    assert labels["os"] == "Module"


def test_manifest_depends_on_persisted_and_purgeable(gi, tmp_path):
    index, mgr = gi
    fp = f"{tmp_path}/pyproject.toml".replace("\\", "/")
    src = (
        '[tool.poetry]\nname = "srv"\n[tool.poetry.dependencies]\nfastapi = "^0.111"\n'
    )
    index.build_from_documents([_manifest(fp, src)])
    assert ("srv", "fastapi") in _edges(mgr, "depends_on")
    # Re-index with the dep removed → stale edge gone.
    src2 = '[tool.poetry]\nname = "srv"\n[tool.poetry.dependencies]\n'
    index.build_from_documents([_manifest(fp, src2)])
    assert ("srv", "fastapi") not in _edges(mgr, "depends_on")


def test_folder_swept_when_last_file_purged(gi, tmp_path):
    index, mgr = gi
    root = str(tmp_path).replace("\\", "/")
    fp = f"{root}/pkg/only.py"
    index.build_from_documents([_pyfile(fp, "def f():\n    pass\n")], root=root)
    assert f"{root}/pkg" in _labels(mgr)
    # Simulate the file disappearing: purge + sweeps, then rebuild empty batch.
    mgr.invalidate_by_source_file(fp, domain="code")
    mgr.sweep_orphan_nodes(domain="code")
    assert mgr.sweep_empty_folders(domain="code") >= 1
    assert f"{root}/pkg" not in _labels(mgr)


def test_lsp_references_merge_when_enabled(gi, monkeypatch):
    index, mgr = gi
    from brainpalace_server.lsp import servers

    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: lang == "python")

    class _FakeLsp:
        def extract_from_symbols(self, symbols, source_chunk_id=None):
            return []

        def extract_references(self, sites, source_chunk_id=None):
            from brainpalace_server.models.graph import GraphTriple

            assert sites, "ref sites must be forwarded"
            return [
                GraphTriple(
                    subject="make",
                    predicate="references",
                    object="Widget",
                    subject_id="m.py:make",
                    object_id="t.py:Widget",
                    subject_name="make",
                    object_name="Widget",
                    subject_type="Function",
                    object_type="Class",
                )
            ]

    monkeypatch.setattr(index, "_get_lsp_extractor", lambda root=None: _FakeLsp())
    src = "def make(w: Widget):\n    pass\n"
    index.build_from_documents([_pyfile("m.py", src)])
    assert ("m.py:make", "t.py:Widget") in _edges(mgr, "references")


def test_identity_flag_is_v3(gi):
    _, mgr = gi
    assert mgr.needs_code_identity_rebuild() is True
    mgr.mark_code_identity_rebuilt()
    assert mgr.needs_code_identity_rebuild() is False
    row = mgr._graph_store._conn.execute(
        "SELECT value FROM meta WHERE key = 'code_identity_v3'"
    ).fetchone()
    assert row is not None
