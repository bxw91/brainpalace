"""Interactive BM25 lemma-engine opt-in during `brainpalace init`.

Mirrors the GraphRAG doc-extraction opt-in: a "yes" writes
``bm25.engine: lemma`` AND installs the optional ``simplemma`` extra
(``lemma-hr``); a "no" writes nothing new (sparse-config invariant) and
never installs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from brainpalace_cli.commands import init as initmod


def _invoke(tmp_path, monkeypatch, *, args, stdin, plugin=True):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: plugin)
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)  # force interactive
    return CliRunner().invoke(
        initmod.init_command, ["--path", str(tmp_path), *args], input=stdin
    )


def _read_cfg(tmp_path) -> dict:
    cfg_path = Path(tmp_path) / ".brainpalace" / "config.yaml"
    return yaml.safe_load(cfg_path.read_text()) or {}


# Flags that suppress all the OTHER per-feature prompts so the only remaining
# interactive questions are: graphrag-extract, reranker-gate, lemma, then the
# final Proceed gate (estimate is skipped on --no-start).
_SUPPRESS = [
    "--no-start",
    "--no-sessions",
    "--no-extract",
    "--no-git-history",
    "--no-graphrag-extract",
    "--no-archive",
]


def test_decline_lemma_writes_no_lemma_engine_and_no_install(tmp_path, monkeypatch):
    # Accept the grid without touching the BM25 division → engine stays stem,
    # no install; then Proceed.
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        r = _invoke(tmp_path, monkeypatch, args=_SUPPRESS, stdin="c\ny\n")
    assert r.exit_code == 0, r.output
    cfg = _read_cfg(tmp_path)
    # No global XDG config in this tmp project → init seeds code defaults, so the
    # decline path must leave engine at the seeded "stem" (NOT "lemma", and NOT
    # silently flipped). Locking the exact value catches a regression that writes
    # "lemma" on a decline, which the old `!= "lemma"` check would also catch but
    # which a future bug writing some other engine would slip past.
    assert cfg.get("bm25", {}).get("engine") == "stem"
    ensure.assert_not_called()


def test_enable_lemma_writes_engine_and_installs(tmp_path, monkeypatch):
    # Drill the BM25 division (9): Enter past language, set engine=lemma, Enter
    # past detect + min-confidence, [C]ontinue, Proceed → engine lemma +
    # ensure_extra (bm25.engine is now a plain grid field reconciled by
    # _reconcile_optional_deps).
    # Grid: Embedding=1, Summarization=2, Reranker=3 → BM25 is division 4.
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        r = _invoke(
            tmp_path, monkeypatch, args=_SUPPRESS, stdin="4\n\nlemma\n\n\nc\ny\n"
        )
    assert r.exit_code == 0, r.output
    cfg = _read_cfg(tmp_path)
    assert cfg["bm25"]["engine"] == "lemma"
    ensure.assert_called_once_with("lemma-hr", assume_yes=True)


@pytest.mark.parametrize("engine", ["lemma", "stem"])
def test_explicit_bm25_engine_flag_skips_lemma_prompt(tmp_path, monkeypatch, engine):
    # --bm25-engine passed → no interactive lemma question, and the flag's
    # value is locked into the written config.
    with patch("brainpalace_cli.optional_deps.ensure_extra"):
        r = _invoke(
            tmp_path,
            monkeypatch,
            args=[*_SUPPRESS, "--bm25-engine", engine],
            stdin="c\ny\n",  # accept the grid, Proceed
        )
    assert r.exit_code == 0, r.output
    assert "lemmatization for BM25" not in r.output.lower().replace("\n", " ")
    cfg = _read_cfg(tmp_path)
    assert cfg["bm25"]["engine"] == engine
