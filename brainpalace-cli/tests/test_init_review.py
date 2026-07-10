"""`brainpalace init` registry-driven review screen.

The review screen is the last interactive step before any index data is written.
It shows the resolved config by division and lets the user edit the model fields
init does not already ask. Accepting with no edits writes nothing (sparse
invariant); [E]xit cancels with a clean rollback; an edit is deep-set into
config.yaml. consent fields are routed to init's existing gated prompts (a no-op
callback here), never re-prompted as plain fields.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands import init as initmod

# Suppress the flag-driven capabilities so the grid is the first interactive
# surface. Grid-first flow: the review grid runs BEFORE any consent prompt, so
# the FIRST keystrokes drive the grid; the Proceed gate follows.
_SUPPRESS = [
    "--no-start",
    "--no-sessions",
    "--no-extract",
    "--no-git-history",
    "--no-graphrag-extract",
    "--no-archive",
]
# Proceed gate answer, fed AFTER the grid's [C]ontinue.
_PROCEED = "y\n"


def _invoke(tmp_path, monkeypatch, stdin):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    return CliRunner().invoke(
        initmod.init_command, ["--path", str(tmp_path), *_SUPPRESS], input=stdin
    )


def _cfg(tmp_path) -> dict:
    p = Path(tmp_path) / ".brainpalace" / "config.yaml"
    return yaml.safe_load(p.read_text()) or {}


def test_review_continue_writes_nothing_extra(tmp_path, monkeypatch):
    r = _invoke(tmp_path, monkeypatch, "c\n" + _PROCEED)
    assert r.exit_code == 0, r.output
    cfg = _cfg(tmp_path)
    # Accepting the review with no edits must not dump default sections.
    assert "usage_metrics" not in cfg
    assert "query_log" not in cfg


def test_review_exit_rolls_back_fresh(tmp_path, monkeypatch):
    # [E]xit the grid cancels init with a clean rollback (no Proceed gate reached).
    r = _invoke(tmp_path, monkeypatch, "e\n")
    assert r.exit_code == 0, r.output
    assert "Cancelled" in r.output
    assert not (Path(tmp_path) / ".brainpalace").exists()


def test_review_edit_is_persisted_sparsely(tmp_path, monkeypatch):
    # Drill the Usage Metrics division (19): keep enabled (y), set retain_days=30,
    # [C]ontinue, then Proceed.
    # Grid order: ... 11=Chat Session : Archiving, 12=Chat Session : Vector Indexing,
    # 13=Chat Session : Summarization, 14=Extraction Engine, 15=Server, 16=Server Mode,
    # 17=Query Log, 18=Retrieval Ranking, 19=Usage Metrics.
    r = _invoke(tmp_path, monkeypatch, "19\ny\n30\nc\n" + _PROCEED)
    assert r.exit_code == 0, r.output
    assert _cfg(tmp_path)["usage_metrics"]["retain_days"] == 30


def test_review_consent_field_not_plain_prompted(tmp_path, monkeypatch):
    # Drilling the Chat Session : Vector Indexing division (12) routes the consent
    # field (enabled) to the rich on_consent callback — never a plain ask_field. The
    # gate leads; declining it (n) fires the rich billable warning and leaves embedding
    # OFF, skipping the governed fields. Then [C]ontinue + Proceed.
    # Grid order: 11=Chat Session : Archiving, 12=Chat Session : Vector Indexing.
    r = _invoke(tmp_path, monkeypatch, "12\nn\nc\n" + _PROCEED)
    assert r.exit_code == 0, r.output
    # The consent prompt surfaced (rich warning), not a plain ask_field.
    assert "embedding chat transcripts is billable" in r.output
    assert _cfg(tmp_path).get("session_indexing", {}).get("enabled") is False


# ── Task 4: re-init drops into the unified editor ────────────────────────────


def _make_initialized(tmp_path):
    """Create a minimal already-initialized project (config.json + config.yaml)."""
    state = tmp_path / ".brainpalace"
    state.mkdir(parents=True)
    # config.json is the re-init sentinel (resolved_state_dir / "config.json")
    (state / "config.json").write_text(_json.dumps({"project_root": str(tmp_path)}))
    (state / "config.yaml").write_text("embedding:\n  provider: openai\n")
    return state


_REINIT_FLAGS = [
    "--no-start",
    "--no-sessions",
    "--no-extract",
    "--no-git-history",
    "--no-graphrag-extract",
    "--no-archive",
    "--no-reranking",
]


def test_reinit_interactive_edits_existing_config(tmp_path, monkeypatch):
    state = _make_initialized(tmp_path)
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    # All consent flags passed. Grid-first re-init flow:
    #   keep (pre-existing-index prompt)
    #   grid1 (review): [C]ontinue
    #   Proceed? → Y
    #   grid2 (re-init editor — the one that persists edits): drill embedding (1),
    #   set provider=ollama, Enter past model/api_key/api_key_env/base_url/params,
    #   [C]ontinue.
    # Gate-first drill: embedding has no gates. All fields shown (incl. advanced
    # api_key_env and hidden api_key/params) — 5 fields after provider.
    result = CliRunner().invoke(
        initmod.init_command,
        ["--path", str(tmp_path), "--bm25-engine=stem", *_REINIT_FLAGS],
        input="keep\nc\nY\n1\nollama\n\n\n\n\n\nc\n",
    )
    assert result.exit_code == 0, result.output
    assert (
        yaml.safe_load((state / "config.yaml").read_text())["embedding"]["provider"]
        == "ollama"
    )


def test_reinit_continue_no_edits_is_idempotent(tmp_path, monkeypatch):
    state = _make_initialized(tmp_path)
    # Pre-populate config.yaml with a value we can assert is NOT changed by editor.
    (state / "config.yaml").write_text("embedding:\n  provider: openai\n")
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    # keep → grid1 [C]ontinue → Proceed Y → grid2 (editor) [C]ontinue (no edits).
    # The editor must not change embedding.provider from openai.
    result = CliRunner().invoke(
        initmod.init_command,
        ["--path", str(tmp_path), "--bm25-engine=stem", *_REINIT_FLAGS],
        input="keep\nc\nY\nc\n",
    )
    assert result.exit_code == 0, result.output
    cfg = yaml.safe_load((state / "config.yaml").read_text())
    # The editor's no-edit Continue must not clobber the existing embedding.provider.
    assert cfg.get("embedding", {}).get("provider") == "openai"
