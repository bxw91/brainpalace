"""Live LSP smoke test against a real pyright (Phase 150).

Skips automatically when ``pyright-langserver`` is not installed, so CI stays
green without any language server. Run locally after ``npm i -g pyright``.
"""

from __future__ import annotations

import shutil
import textwrap

import pytest

from brainpalace_server.lsp.client import LspClient
from brainpalace_server.lsp.cross_refs import extract_cross_refs

pytestmark = pytest.mark.skipif(
    shutil.which("pyright-langserver") is None,
    reason="pyright-langserver not installed",
)


def test_pyright_defined_at(tmp_path) -> None:
    src = tmp_path / "mod.py"
    src.write_text(
        textwrap.dedent(
            """
            def helper():
                return 1

            def caller():
                return helper()
            """
        )
    )
    client = LspClient.spawn(["pyright-langserver", "--stdio"])
    try:
        client.initialize(root_uri=f"file://{tmp_path}")
        client.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": f"file://{src}",
                    "languageId": "python",
                    "version": 1,
                    "text": src.read_text(),
                }
            },
        )
        triples = extract_cross_refs(
            client,
            file_path=str(src),
            symbol_name="helper",
            line=1,  # 0-based line of `def helper`
            character=4,
            source_chunk_id="live",
        )
    finally:
        client.shutdown()

    # We at least expect a defined-at edge for the symbol.
    assert any(t.predicate == "defined-at" for t in triples)
