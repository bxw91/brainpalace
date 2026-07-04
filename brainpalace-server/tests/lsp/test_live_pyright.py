"""Live LSP smoke against a real pyright (Plan 5 acceptance).

Skips when ``pyright-langserver`` is not installed. Exercises the PRODUCTION
path: LspCrossRefExtractor with root_uri + didOpen + fqname resolver — the
spec's bar is a real cross-file `calls` edge, verified by test, not eyeball.
"""

from __future__ import annotations

import shutil
import textwrap

import pytest

from brainpalace_server.indexing.code_symbol_extractor import (
    extract_python_symbols,
)
from brainpalace_server.lsp import servers
from brainpalace_server.lsp.extractor import LspCrossRefExtractor

pytestmark = pytest.mark.skipif(
    shutil.which("pyright-langserver") is None,
    reason="pyright-langserver not installed",
)


def test_pyright_cross_file_calls(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(servers, "is_language_enabled", lambda lang: lang == "python")
    util = tmp_path / "util.py"
    util.write_text("def helper():\n    return 1\n")
    main = tmp_path / "main.py"
    main.write_text(
        textwrap.dedent(
            """
            from util import helper


            def caller():
                return helper()
            """
        )
    )
    ext = LspCrossRefExtractor(root_uri=f"file://{tmp_path}")
    try:
        fs = extract_python_symbols(str(main), main.read_text())
        triples = ext.extract_from_symbols(fs.symbols)
    finally:
        ext.close()

    calls = {
        (t.effective_subject_id, t.effective_object_id)
        for t in triples
        if t.predicate == "calls"
    }
    assert (f"{main}:caller", f"{util}:helper") in calls
