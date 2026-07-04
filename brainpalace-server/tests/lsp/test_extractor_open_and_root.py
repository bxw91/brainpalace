# brainpalace-server/tests/lsp/test_extractor_open_and_root.py
"""Plan 5 Task 3 — real servers need a workspace root and opened documents."""

from brainpalace_server.indexing.code_symbol_extractor import SymbolDef
from brainpalace_server.lsp import servers
from brainpalace_server.lsp.extractor import LspCrossRefExtractor


class RecordingClient:
    def __init__(self):
        self.initialized_root = None
        self.notifications = []

    def initialize(self, root_uri):
        self.initialized_root = root_uri

    def notify(self, method, params=None):
        self.notifications.append((method, params))

    def request(self, method, params=None):
        return None  # no results — we only assert the protocol prelude

    def shutdown(self):
        pass


def _sym(path):
    return SymbolDef(
        symbol_id=f"{path}:top",
        fqname="top",
        short="top",
        kind="Function",
        language="python",
        file_path=path,
        line=0,
        character=4,
    )


def test_root_uri_reaches_initialize_and_file_is_opened(tmp_path, monkeypatch):
    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: lang == "python")
    src = tmp_path / "m.py"
    src.write_text("def top():\n    pass\n")
    client = RecordingClient()
    ext = LspCrossRefExtractor(
        root_uri=f"file://{tmp_path}", client_factory=lambda lang: client
    )
    ext.extract_from_symbols([_sym(str(src))])
    assert client.initialized_root == f"file://{tmp_path}"
    opens = [p for m, p in client.notifications if m == "textDocument/didOpen"]
    assert len(opens) == 1
    assert opens[0]["textDocument"]["uri"] == f"file://{src}"
    assert "def top" in opens[0]["textDocument"]["text"]
    # Second pass over the same file: no duplicate didOpen.
    ext.extract_from_symbols([_sym(str(src))])
    assert len([1 for m, _ in client.notifications if m == "textDocument/didOpen"]) == 1


def test_missing_file_is_failsoft(tmp_path, monkeypatch):
    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: lang == "python")
    client = RecordingClient()
    ext = LspCrossRefExtractor(client_factory=lambda lang: client)
    # File does not exist on disk — must not raise, just no didOpen.
    assert ext.extract_from_symbols([_sym(str(tmp_path / "gone.py"))]) == []
    assert not [1 for m, _ in client.notifications if m == "textDocument/didOpen"]
