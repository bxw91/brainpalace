from brainpalace_server.rehome.swap import (
    SwappedEdge,
    SwappedNode,
    rehome_folder_record,
    rehome_graph_edge,
    rehome_graph_node,
    rehome_reference_entry,
    rekey_manifest,
    swap_chunk_metadata,
    swap_exclude_patterns,
)
from brainpalace_server.services.folder_manager import FolderRecord
from brainpalace_server.services.manifest_tracker import FileRecord, FolderManifest
from brainpalace_server.storage.reference_catalog_store import ReferenceEntry, ref_id
from brainpalace_server.storage.sqlite_graph_store import _edge_id as _store_edge_id


def test_swap_exclude_patterns_swaps_only_in_root_absolutes():
    out = swap_exclude_patterns(
        [
            "/old/root/build",  # absolute, in-root  -> swapped
            "**/node_modules/**",  # glob               -> verbatim
            "*.log",  # glob               -> verbatim
            "/somewhere/else/cache",  # absolute, out-root -> verbatim
            "/old/root/**/dist",  # absolute glob in-root -> prefix swapped
        ],
        "/old/root",
        "/new/home",
    )
    assert out == [
        "/new/home/build",
        "**/node_modules/**",
        "*.log",
        "/somewhere/else/cache",
        "/new/home/**/dist",
    ]


def test_swap_exclude_patterns_empty():
    assert swap_exclude_patterns([], "/old/root", "/new/home") == []


def _rec(folder_path):
    return FolderRecord(
        folder_path=folder_path,
        chunk_count=3,
        last_indexed="2026-07-11T00:00:00+00:00",
        chunk_ids=["a_0", "a_1", "a_2"],
        watch_mode="auto",
        include_code=True,
        source="init",
        authority="authoritative",
    )


def test_rehome_folder_record_swaps_in_root():
    out = rehome_folder_record(_rec("/old/root/sub"), "/old/root", "/new/home")
    assert out.folder_path == "/new/home/sub"
    assert out.chunk_ids == ["a_0", "a_1", "a_2"]  # opaque ids untouched
    assert out.watch_mode == "auto" and out.include_code is True


def test_rehome_folder_record_leaves_external():
    ext = _rec("/somewhere/else/docs")
    out = rehome_folder_record(ext, "/old/root", "/new/home")
    assert out.folder_path == "/somewhere/else/docs"


def test_rekey_manifest_swaps_folder_and_file_keys():
    m = FolderManifest(
        folder_path="/old/root/pkg",
        files={
            "/old/root/pkg/a.py": FileRecord(
                checksum="c1", mtime=1.0, chunk_ids=["a_0"]
            ),
            "/old/root/pkg/sub/b.py": FileRecord(
                checksum="c2", mtime=2.0, chunk_ids=["b_0", "b_1"]
            ),
        },
    )
    out = rekey_manifest(m, "/old/root", "/new/home")

    assert out.folder_path == "/new/home/pkg"
    assert set(out.files.keys()) == {
        "/new/home/pkg/a.py",
        "/new/home/pkg/sub/b.py",
    }
    # FileRecord values carried through verbatim (chunk ids are opaque)
    assert out.files["/new/home/pkg/a.py"].checksum == "c1"
    assert out.files["/new/home/pkg/a.py"].chunk_ids == ["a_0"]
    assert out.files["/new/home/pkg/sub/b.py"].chunk_ids == ["b_0", "b_1"]
    # input not mutated
    assert "/old/root/pkg/a.py" in m.files


def test_rehome_reference_entry_swaps_and_recomputes_id():
    src = "/old/root/data/spec.pdf"
    ptr = "/old/root/data/spec.pdf#p3"
    e = ReferenceEntry(
        id=ref_id(ptr, src),
        domain="docs",
        source=src,
        source_id=src,
        pointer=ptr,
    )
    out = rehome_reference_entry(e, "/old/root", "/new/home")

    new_src = "/new/home/data/spec.pdf"
    new_ptr = "/new/home/data/spec.pdf#p3"
    assert out.source == new_src
    assert out.pointer == new_ptr
    assert out.source_id == new_src
    assert out.id == ref_id(new_ptr, new_src)
    assert out.domain == "docs"


def test_rehome_reference_entry_out_of_root_unchanged():
    src = "https://example.com/x"
    ptr = "https://example.com/x#frag"
    e = ReferenceEntry(
        id=ref_id(ptr, src), domain="web", source=src, source_id=src, pointer=ptr
    )
    out = rehome_reference_entry(e, "/old/root", "/new/home")
    assert out.id == e.id and out.source == src and out.pointer == ptr


def test_rehome_graph_node_swaps_id_and_path_properties():
    out = rehome_graph_node(
        "/old/root/pkg/mod.py:Foo.bar",
        {"path": "/old/root/pkg/mod.py", "kind": "Method"},
        "/old/root",
        "/new/home",
    )
    assert isinstance(out, SwappedNode)
    assert out.id == "/new/home/pkg/mod.py:Foo.bar"
    assert out.properties["path"] == "/new/home/pkg/mod.py"
    assert out.properties["kind"] == "Method"  # non-path prop untouched


def test_rehome_graph_node_exact_root_and_external():
    # Folder node whose id IS old_root exactly
    out = rehome_graph_node("/old/root", {}, "/old/root", "/new/home")
    assert out.id == "/new/home"
    # external code node left verbatim
    ext = rehome_graph_node("os.path:join", {}, "/old/root", "/new/home")
    assert ext.id == "os.path:join"


def test_rehome_graph_edge_recomputes_id_from_swapped_endpoints():
    out = rehome_graph_edge(
        source_id="/old/root/pkg",
        target_id="/old/root/pkg/mod.py",
        label="contains",
        source_file="/old/root/pkg/mod.py",
        old_root="/old/root",
        new_root="/new/home",
    )
    assert isinstance(out, SwappedEdge)
    assert out.source_id == "/new/home/pkg"
    assert out.target_id == "/new/home/pkg/mod.py"
    assert out.source_file == "/new/home/pkg/mod.py"
    # id recomputed, NOT string-replaced
    assert out.id == _store_edge_id("/new/home/pkg", "contains", "/new/home/pkg/mod.py")


def test_rehome_graph_edge_none_source_file_and_external_target():
    out = rehome_graph_edge(
        source_id="/old/root/a.py",
        target_id="os.path:join",  # external endpoint stays
        label="calls",
        source_file=None,
        old_root="/old/root",
        new_root="/new/home",
    )
    assert out.source_id == "/new/home/a.py"
    assert out.target_id == "os.path:join"
    assert out.source_file is None
    assert out.id == _store_edge_id("/new/home/a.py", "calls", "os.path:join")


def test_swap_edge_id_matches_store_edge_id():
    # parity guard: our replicated _edge_id must equal the store's for any triple
    from brainpalace_server.rehome.swap import _edge_id as _rehome_edge_id

    for s, lbl, t in [
        ("/x/a", "calls", "/x/b"),
        ("a:Foo", "references", "b:Bar"),
        ("", "contains", ""),
    ]:
        assert _rehome_edge_id(s, lbl, t) == _store_edge_id(s, lbl, t)


def test_swap_chunk_metadata_swaps_d12_keys():
    out = swap_chunk_metadata(
        {
            "source": "/old/root/a.py",
            "file_path": "/old/root/a.py",
            "path": "/old/root/sess.jsonl",
            "page_label": "/old/root/a.py",  # multi-part loader stashed a path here
            "language": "python",
        },
        "/old/root",
        "/new/home",
    )
    assert out["source"] == "/new/home/a.py"
    assert out["file_path"] == "/new/home/a.py"
    assert out["path"] == "/new/home/sess.jsonl"
    assert out["page_label"] == "/new/home/a.py"
    assert out["language"] == "python"


def test_swap_chunk_metadata_leaves_genuine_label_and_external():
    out = swap_chunk_metadata(
        {"source": "/somewhere/else/x.md", "page_label": "p. 4", "n": 3},
        "/old/root",
        "/new/home",
    )
    assert out == {"source": "/somewhere/else/x.md", "page_label": "p. 4", "n": 3}
