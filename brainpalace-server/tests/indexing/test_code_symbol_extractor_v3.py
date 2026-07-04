"""Plan 3 — typed kinds, File/Folder, decorators/endpoints, imports, ref sites."""

from brainpalace_server.indexing.code_symbol_extractor import (
    extract_python_symbols,
)

KIND_SRC = """
import enum
from typing import Protocol


class Color(enum.Enum):
    RED = 1


class Greeter(Protocol):
    def greet(self):
        pass


class Widget:
    def run(self):
        pass


def top():
    pass
"""

DECOR_SRC = """
import pytest


@pytest.fixture
def fx():
    pass


@router.get("/things")
def list_things():
    pass
"""

ANN_SRC = """
class Widget:
    pass


def make(w: Widget, n: int) -> Widget:
    pass
"""


def _typed(fs):
    out = {}
    for t in fs.triples:
        if t.subject_type:
            out[t.effective_subject_id] = t.subject_type
        if t.object_type:
            out[t.effective_object_id] = t.object_type
    return out


def _ids(fs):
    return {
        (t.effective_subject_id, t.predicate, t.effective_object_id) for t in fs.triples
    }


def test_precise_kinds_enum_interface_method():
    fs = extract_python_symbols("pkg/mod.py", KIND_SRC)
    types = _typed(fs)
    assert types["pkg/mod.py:Color"] == "Enum"
    assert types["pkg/mod.py:Greeter"] == "Interface"
    assert types["pkg/mod.py:Widget"] == "Class"
    assert types["pkg/mod.py:Widget.run"] == "Method"
    assert types["pkg/mod.py:Greeter.greet"] == "Method"
    assert types["pkg/mod.py:top"] == "Function"


def test_file_node_replaces_module():
    fs = extract_python_symbols("pkg/mod.py", KIND_SRC)
    types = _typed(fs)
    assert types["pkg/mod.py"] == "File"
    names = {}
    for t in fs.triples:
        names[t.effective_subject_id] = t.subject_name
        names[t.effective_object_id] = t.object_name
    assert names["pkg/mod.py"] == "mod.py"  # display = basename


def test_folder_chain_with_root():
    fs = extract_python_symbols(
        "proj/pkg/sub/mod.py", "def f():\n    pass\n", root="proj"
    )
    ids = _ids(fs)
    assert ("proj", "contains", "proj/pkg") in ids
    assert ("proj/pkg", "contains", "proj/pkg/sub") in ids
    assert ("proj/pkg/sub", "contains", "proj/pkg/sub/mod.py") in ids
    types = _typed(fs)
    assert types["proj/pkg"] == "Folder"
    assert types["proj/pkg/sub/mod.py"] == "File"
    # Folder->Folder edges are shared: no per-file provenance.
    chain = [
        t
        for t in fs.triples
        if t.subject_type == "Folder" and t.object_type == "Folder"
    ]
    assert chain and all(t.source_file is None for t in chain)
    # Folder->File edge IS per-file provenance.
    leaf = next(
        t for t in fs.triples if t.subject_type == "Folder" and t.object_type == "File"
    )
    assert leaf.source_file == "proj/pkg/sub/mod.py"


def test_no_folder_chain_without_root():
    fs = extract_python_symbols("proj/pkg/mod.py", "def f():\n    pass\n")
    assert not any(t.subject_type == "Folder" for t in fs.triples)


def test_decorated_by_and_endpoint():
    fs = extract_python_symbols("api/r.py", DECOR_SRC)
    ids = _ids(fs)
    assert ("api/r.py:fx", "decorated_by", "decorator:pytest.fixture") in ids
    assert (
        "api/r.py:list_things",
        "decorated_by",
        "decorator:router.get",
    ) in ids
    assert (
        "endpoint:GET /things",
        "handled_by",
        "api/r.py:list_things",
    ) in ids
    types = _typed(fs)
    assert types["decorator:pytest.fixture"] == "Decorator"
    assert types["endpoint:GET /things"] == "Endpoint"


def test_import_specs_collected():
    fs = extract_python_symbols("pkg/mod.py", DECOR_SRC)
    assert any(
        s.module == "pytest" and s.level == 0 and s.names == [] for s in fs.imports
    )
    fs2 = extract_python_symbols(
        "pkg/mod.py", "from .util import helper\nfrom a.b import c\n"
    )
    assert any(
        s.module == "util" and s.level == 1 and s.names == ["helper"]
        for s in fs2.imports
    )
    assert any(
        s.module == "a.b" and s.level == 0 and s.names == ["c"] for s in fs2.imports
    )


def test_ref_sites_from_annotations_skip_builtins():
    fs = extract_python_symbols("pkg/mod.py", ANN_SRC)
    names = [(s.caller_id, s.name) for s in fs.ref_sites]
    assert names.count(("pkg/mod.py:make", "Widget")) == 2  # param + return
    assert not any(n == "int" for _, n in names)  # builtins skipped
    site = fs.ref_sites[0]
    assert site.file_path == "pkg/mod.py"
    assert site.language == "python"
    assert site.line == 5  # `def make` is source line 6 (1-based)
    assert site.character > 0
