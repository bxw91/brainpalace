"""LspCrossRefExtractor: gating + metadata → triplets (Phase 150)."""

from __future__ import annotations

import pytest

from brainpalace_server.config import settings
from brainpalace_server.lsp.extractor import LspCrossRefExtractor


class FakeClient:
    def __init__(self) -> None:
        self.initialized = False

    def initialize(self, root_uri, capabilities=None):
        self.initialized = True
        return {}

    def request(self, method, params=None):
        if method == "textDocument/definition":
            return [{"uri": "file://pkg/mod.py", "range": {"start": {"line": 9}}}]
        return None

    def shutdown(self):
        pass


def _meta(**kw):
    base = {
        "file_path": "pkg/mod.py",
        "symbol_name": "handler",
        "symbol_type": "function",
        "start_line": 10,
        "language": "python",
    }
    base.update(kw)
    return base


def _extractor(enabled: bool) -> LspCrossRefExtractor:
    fake = FakeClient()
    return LspCrossRefExtractor(
        root_uri="file:///proj",
        client_factory=lambda lang: fake if enabled else None,
    )


def test_disabled_language_yields_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "")  # inert
    ex = _extractor(enabled=True)
    assert ex.extract_from_metadata(_meta(), source_chunk_id="c1") == []


def test_enabled_language_extracts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "python")
    ex = _extractor(enabled=True)
    triples = ex.extract_from_metadata(_meta(), source_chunk_id="c1")
    assert any(t.predicate == "defined-at" for t in triples)


def test_missing_symbol_or_line_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "python")
    ex = _extractor(enabled=True)
    assert ex.extract_from_metadata(_meta(symbol_name=None), "c1") == []
    assert ex.extract_from_metadata(_meta(start_line=None), "c1") == []


def test_unavailable_server_is_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "python")
    ex = _extractor(enabled=False)  # factory returns None (spawn failed)
    assert ex.extract_from_metadata(_meta(), "c1") == []


def test_language_inferred_from_path_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "python")
    ex = _extractor(enabled=True)
    triples = ex.extract_from_metadata(_meta(language=None), "c1")
    assert any(t.predicate == "defined-at" for t in triples)
