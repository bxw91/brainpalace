# brainpalace-server/tests/lsp/test_target_fqname.py
"""Plan 5 Task 5 — LSP method targets must merge with AST `file:C.m` ids."""

from brainpalace_server.lsp import servers
from brainpalace_server.lsp.cross_refs import extract_cross_refs
from brainpalace_server.lsp.extractor import LspCrossRefExtractor


class FakeClient:
    def __init__(self, responses):
        self.responses = responses

    def initialize(self, root_uri):
        pass

    def notify(self, method, params=None):
        pass

    def request(self, method, params=None):
        return self.responses.get(method)

    def shutdown(self):
        pass


def _ch_item(name, path, line):
    return {
        "name": name,
        "uri": f"file://{path}",
        "kind": 6,  # Method
        "range": {"start": {"line": line, "character": 4}},
    }


def test_extract_cross_refs_uses_resolver_for_targets():
    client = FakeClient(
        {
            "textDocument/prepareCallHierarchy": [_ch_item("top", "/p/mod.py", 0)],
            "callHierarchy/outgoingCalls": [
                {"to": _ch_item("m", "/p/other.py", 4)}  # short name from LSP
            ],
        }
    )
    resolver_calls = []

    def resolver(path, line, fallback):
        resolver_calls.append((path, line, fallback))
        return "C.m" if path == "/p/other.py" and line == 4 else fallback

    triples = extract_cross_refs(
        client,
        file_path="/p/mod.py",
        symbol_name="top",
        line=0,
        character=4,
        target_fqname=resolver,
    )
    call = next(t for t in triples if t.predicate == "calls")
    assert call.effective_object_id == "/p/other.py:C.m"  # fqname, not "m"
    assert resolver_calls  # resolver actually consulted


def test_extractor_fqname_at_maps_def_line(tmp_path, monkeypatch):
    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: lang == "python")
    target = tmp_path / "other.py"
    target.write_text("class C:\n    def m(self):\n        pass\n")
    ext = LspCrossRefExtractor(client_factory=lambda lang: None)
    # `def m` is 0-based line 1.
    assert ext._fqname_at(str(target), 1, "m") == "C.m"
    # Unknown line / non-Python path fall back to the reported name.
    assert ext._fqname_at(str(target), 99, "m") == "m"
    assert ext._fqname_at(str(tmp_path / "x.md"), 0, "m") == "m"
