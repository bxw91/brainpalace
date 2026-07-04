from brainpalace_server.indexing.code_symbol_extractor import extract_python_file

SRC = """
def top():
    pass

class C:
    def m(self):
        pass

def other():
    pass
"""


def _ids(triples):
    out = set()
    for t in triples:
        out.add((t.effective_subject_id, t.predicate, t.effective_object_id))
    return out


def test_every_function_and_method_is_covered():
    triples = extract_python_file("pkg/mod.py", SRC)
    ids = _ids(triples)
    # module contains top-level symbols
    assert ("pkg/mod.py", "contains", "pkg/mod.py:top") in ids
    assert ("pkg/mod.py", "contains", "pkg/mod.py:other") in ids
    assert ("pkg/mod.py", "contains", "pkg/mod.py:C") in ids
    # class contains its method (qualified)
    assert ("pkg/mod.py:C", "contains", "pkg/mod.py:C.m") in ids
    # defined_in inverse present for the method
    assert ("pkg/mod.py:C.m", "defined_in", "pkg/mod.py") in ids


def test_display_names_are_short():
    triples = extract_python_file("pkg/mod.py", SRC)
    by_id = {}
    for t in triples:
        by_id[t.effective_subject_id] = t.subject_name
        by_id[t.effective_object_id] = t.object_name
    assert by_id["pkg/mod.py:C.m"] == "m"
    assert by_id["pkg/mod.py:top"] == "top"


def test_syntax_error_returns_empty():
    assert extract_python_file("bad.py", "def (:::") == []
