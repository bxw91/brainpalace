from brainpalace_server.indexing.code_symbol_extractor import (
    extract_python_file,
    extract_python_symbols,
)

SRC = """
def helper():
    pass

def top():
    helper()
    unknown_external()

class C:
    def m(self):
        self.n()
        helper()

    def n(self):
        pass
"""


def _calls(fs):
    return {
        (t.effective_subject_id, t.effective_object_id)
        for t in fs.triples
        if t.predicate == "calls"
    }


def test_intrafile_function_call_edge():
    fs = extract_python_symbols("pkg/mod.py", SRC)
    assert ("pkg/mod.py:top", "pkg/mod.py:helper") in _calls(fs)


def test_self_method_call_edge():
    fs = extract_python_symbols("pkg/mod.py", SRC)
    assert ("pkg/mod.py:C.m", "pkg/mod.py:C.n") in _calls(fs)


def test_method_calls_top_level_function():
    fs = extract_python_symbols("pkg/mod.py", SRC)
    assert ("pkg/mod.py:C.m", "pkg/mod.py:helper") in _calls(fs)


def test_unresolved_call_is_not_emitted():
    fs = extract_python_symbols("pkg/mod.py", SRC)
    edges = _calls(fs)
    assert not any(o.endswith("unknown_external") for _, o in edges)


def test_symbol_table_has_positions_and_kinds():
    fs = extract_python_symbols("pkg/mod.py", SRC)
    by_fq = {s.fqname: s for s in fs.symbols}
    assert by_fq["top"].kind == "Function"
    assert by_fq["C"].kind == "Class"
    assert by_fq["C.m"].kind == "Method"
    # name token is on the same line as the def, 0-based; 'top' is line 5 (1-based)
    assert by_fq["top"].line == 4
    assert by_fq["top"].character >= 4  # after "def "
    assert by_fq["top"].language == "python"


def test_calls_endpoints_keep_precise_kind():
    fs = extract_python_symbols("pkg/mod.py", SRC)
    call = next(
        t
        for t in fs.triples
        if t.predicate == "calls"
        and t.effective_subject_id == "pkg/mod.py:C.m"
        and t.effective_object_id == "pkg/mod.py:C.n"
    )
    assert call.subject_type == "Method"
    assert call.object_type == "Method"


def test_extract_python_file_still_returns_containment():
    triples = extract_python_file("pkg/mod.py", SRC)
    ids = {
        (t.effective_subject_id, t.predicate, t.effective_object_id) for t in triples
    }
    assert ("pkg/mod.py", "contains", "pkg/mod.py:top") in ids


# Regression: a def nested inside a non-def compound statement (try/if/with/for)
# must be registered in pass 1 so pass 2 (walk_calls) doesn't KeyError on it.
NESTED_IN_BLOCK_SRC = """
def helper():
    pass

try:
    def maybe():
        helper()
except ImportError:
    def maybe():
        pass

if True:
    class Cond:
        def m(self):
            helper()
"""


def test_def_nested_in_block_does_not_crash():
    fs = extract_python_symbols("pkg/mod.py", NESTED_IN_BLOCK_SRC)
    ids = {s.symbol_id for s in fs.symbols}
    assert "pkg/mod.py:maybe" in ids
    assert "pkg/mod.py:Cond.m" in ids


def test_call_inside_conditionally_defined_symbol_is_captured():
    fs = extract_python_symbols("pkg/mod.py", NESTED_IN_BLOCK_SRC)
    edges = _calls(fs)
    assert ("pkg/mod.py:maybe", "pkg/mod.py:helper") in edges
    assert ("pkg/mod.py:Cond.m", "pkg/mod.py:helper") in edges
