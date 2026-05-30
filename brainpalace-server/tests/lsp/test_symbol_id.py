"""Symbol-Id + LSP relation vocab (Phase 150)."""

from __future__ import annotations

from brainpalace_server.models.graph import (
    LSP_RELATIONS,
    symbol_id,
)


def test_symbol_id_format() -> None:
    assert symbol_id("a/b.py", "Foo.bar") == "a/b.py:Foo.bar"


def test_symbol_id_normalises_separators() -> None:
    assert symbol_id("a\\b.py", "Foo") == "a/b.py:Foo"


def test_symbol_id_strips_and_requires_parts() -> None:
    assert symbol_id("  a.py ", " Foo ") == "a.py:Foo"
    assert symbol_id("", "Foo") == ""
    assert symbol_id("a.py", "") == ""


def test_lsp_relations_closed_vocab() -> None:
    assert set(LSP_RELATIONS) == {
        "calls",
        "called-by",
        "references",
        "extends",
        "implements",
        "defined-at",
        "imports",
    }
