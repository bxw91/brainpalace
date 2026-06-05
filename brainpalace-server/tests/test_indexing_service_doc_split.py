"""Q2: classify indexed document paths into code vs doc by extension."""

from brainpalace_server.services.indexing_service import _classify_documents


def test_classify_splits_code_and_doc_by_extension():
    paths = {"/p/a.py", "/p/b.py", "/p/c.md", "/p/d.html", "/p/e.ts"}
    counts = _classify_documents(paths)
    assert counts["code"] == 3
    assert counts["doc"] == 2
    assert counts["total"] == 5


def test_classify_empty():
    counts = _classify_documents(set())
    assert counts == {"code": 0, "doc": 0, "total": 0}


def test_classify_extension_is_case_insensitive():
    counts = _classify_documents({"/p/A.PY", "/p/B.Md"})
    assert counts["code"] == 1
    assert counts["doc"] == 1
    assert counts["total"] == 2
