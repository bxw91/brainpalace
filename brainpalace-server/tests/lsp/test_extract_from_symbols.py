from brainpalace_server.indexing.code_symbol_extractor import SymbolDef
from brainpalace_server.lsp import servers
from brainpalace_server.lsp.cross_refs import extract_cross_refs
from brainpalace_server.lsp.extractor import LspCrossRefExtractor


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.initialized = False

    def initialize(self, root_uri):
        self.initialized = True

    def request(self, method, params=None):
        return self.responses.get(method)

    def shutdown(self):
        pass


def _ch_item(name, path, line=0):
    return {
        "name": name,
        "uri": f"file://{path}",
        "kind": 12,
        "range": {"start": {"line": line, "character": 0}},
    }


def test_cross_refs_carry_canonical_id_and_short_name():
    client = FakeClient(
        {
            "textDocument/prepareCallHierarchy": [_ch_item("C.m", "pkg/mod.py")],
            "callHierarchy/outgoingCalls": [{"to": _ch_item("db_query", "pkg/db.py")}],
        }
    )
    triples = extract_cross_refs(
        client, file_path="pkg/mod.py", symbol_name="C.m", line=10, character=4
    )
    t = next(t for t in triples if t.predicate == "calls")
    assert t.effective_subject_id == "pkg/mod.py:C.m"
    assert t.effective_object_id == "pkg/db.py:db_query"
    assert t.subject_name == "m"  # short, not qualified
    assert t.object_name == "db_query"


def test_extract_from_symbols_gated_and_keyed(monkeypatch):
    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: lang == "python")
    client = FakeClient(
        {
            "textDocument/prepareCallHierarchy": [_ch_item("top", "pkg/mod.py")],
            "callHierarchy/outgoingCalls": [{"to": _ch_item("helper", "pkg/util.py")}],
        }
    )
    ext = LspCrossRefExtractor(client_factory=lambda lang: client)
    syms = [
        SymbolDef(
            symbol_id="pkg/mod.py:top",
            fqname="top",
            short="top",
            kind="Function",
            language="python",
            file_path="pkg/mod.py",
            line=4,
            character=4,
        )
    ]
    triples = ext.extract_from_symbols(syms)
    assert any(
        t.predicate == "calls"
        and t.effective_subject_id == "pkg/mod.py:top"
        and t.effective_object_id == "pkg/util.py:helper"
        for t in triples
    )


def test_extract_from_symbols_skips_disabled_language(monkeypatch):
    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: False)
    ext = LspCrossRefExtractor(client_factory=lambda lang: None)
    syms = [
        SymbolDef(
            symbol_id="pkg/mod.py:top",
            fqname="top",
            short="top",
            kind="Function",
            language="python",
            file_path="pkg/mod.py",
            line=4,
            character=4,
        )
    ]
    assert ext.extract_from_symbols(syms) == []
