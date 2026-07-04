from brainpalace_server.indexing.code_symbol_extractor import RefSite
from brainpalace_server.lsp import servers
from brainpalace_server.lsp.cross_refs import extract_reference
from brainpalace_server.lsp.extractor import LspCrossRefExtractor


class FakeClient:
    def __init__(self, responses):
        self.responses = responses

    def initialize(self, root_uri):
        pass

    def request(self, method, params=None):
        return self.responses.get(method)

    def shutdown(self):
        pass


_DEF = {
    "textDocument/definition": [
        {"uri": "file://pkg/types.py", "range": {"start": {"line": 3, "character": 6}}}
    ]
}


def test_extract_reference_builds_canonical_triple():
    t = extract_reference(
        FakeClient(_DEF),
        file_path="pkg/mod.py",
        caller_id="pkg/mod.py:make",
        name="types.Widget",
        line=5,
        character=20,
    )
    assert t is not None
    assert t.predicate == "references"
    assert t.effective_subject_id == "pkg/mod.py:make"
    assert t.effective_object_id == "pkg/types.py:Widget"
    assert t.subject_name == "make"
    assert t.object_name == "Widget"


def test_extract_reference_none_without_definition():
    t = extract_reference(
        FakeClient({}),
        file_path="pkg/mod.py",
        caller_id="pkg/mod.py:make",
        name="Widget",
        line=5,
        character=20,
    )
    assert t is None


def _site():
    return RefSite(
        file_path="pkg/mod.py",
        caller_id="pkg/mod.py:make",
        name="Widget",
        line=5,
        character=20,
    )


def test_extract_references_gated(monkeypatch):
    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: lang == "python")
    ext = LspCrossRefExtractor(client_factory=lambda lang: FakeClient(_DEF))
    triples = ext.extract_references([_site()])
    assert len(triples) == 1
    assert triples[0].effective_object_id == "pkg/types.py:Widget"


def test_extract_references_disabled_language(monkeypatch):
    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: False)
    ext = LspCrossRefExtractor(client_factory=lambda lang: None)
    assert ext.extract_references([_site()]) == []
