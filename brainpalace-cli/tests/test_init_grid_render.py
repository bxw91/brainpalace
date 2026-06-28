import click
from click.testing import CliRunner

from brainpalace_cli import config_review as cr


def _render(merged, edits=None):
    @click.command()
    def cmd():
        cr.render_overview(cr._divisions(), merged, edits or {})

    return CliRunner().invoke(cmd, []).output


def test_off_toggleable_division_is_one_line():
    merged = {"reranker": {"enabled": False}}
    out = _render(merged)
    # Reranker line shows only "off" — no provider/model/base_url fields.
    rer = [ln for ln in out.splitlines() if "Reranker" in ln][0]
    assert rer.strip().endswith("off")
    assert "Provider" not in out.split("Reranker")[1].split("Storage")[0]


def test_on_division_shows_all_fields_including_secret():
    merged = {
        "reranker": {
            "enabled": True,
            "provider": "sentence-transformers",
            "model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        }
    }
    out = _render(merged)
    assert "Provider" in out and "sentence-transformers" in out


def test_pure_config_division_always_shows_fields():
    # embedding has no enable toggle -> always expanded.
    merged = {"embedding": {"provider": "openai", "model": "text-embedding-3-large"}}
    out = _render(merged)
    assert "openai" in out and "text-embedding-3-large" in out


def test_empty_field_hidden_from_overview():
    # Empty fields (blank base_url, empty params) are omitted from the overview.
    merged = {"embedding": {"provider": "openai", "model": "m", "base_url": ""}}
    out = _render(merged)
    emb = [ln for ln in out.splitlines() if "Embedding" in ln][0]
    assert "Base url" not in emb
    assert "Params" not in emb
    assert "Provider = openai" in emb and "Model = m" in emb


def test_fmt_empty_renders_parens():
    # The () placeholder still applies where a value IS shown (drill prompts).
    assert cr._fmt(None) == "()"
    assert cr._fmt("") == "()"


def test_dependency_field_hidden_when_selector_inactive():
    # backend=chroma -> the postgres sub-config is omitted entirely.
    merged = {"storage": {"backend": "chroma", "postgres": {"host": "db"}}}
    out = _render(merged)
    sto = [ln for ln in out.splitlines() if "Storage" in ln][0]
    assert "Backend = chroma" in sto
    assert "Postgres" not in sto and "host" not in sto


def test_session_summarization_shows_only_quiescence():
    # session_extraction.mode is REMOVED — the section shows just quiescence_seconds.
    from brainpalace_cli import config_fields as cf

    dps = [s.dotpath for s in cf.group_fields("session_extraction")]
    assert dps == ["session_extraction.quiescence_seconds"]
    merged = {"session_extraction": {"quiescence_seconds": 1800}}
    out = _render(merged)
    ses = [ln for ln in out.splitlines() if "Chat Session : Summarization" in ln][0]
    assert "Mode" not in ses
    assert "Quiescence seconds = 1800" in ses


def test_dependency_field_shown_when_selector_active():
    # backend=postgres -> the (non-empty) postgres sub-config is shown.
    merged = {"storage": {"backend": "postgres", "postgres": {"host": "db"}}}
    out = _render(merged)
    sto = [ln for ln in out.splitlines() if "Storage" in ln][0]
    assert "Backend = postgres" in sto
    assert "Postgres" in sto


def test_session_archiving_and_vector_are_separate_divisions():
    # Archiving (free COPY) and Vector Indexing (billable embed) render as two
    # independent divisions, matching the dashboard. archive ON shows its dir;
    # vector OFF collapses to its gate line (no window/retain detail).
    merged = {
        "session_indexing": {
            "enabled": False,
            "archive": {"enabled": True, "dir": ".brainpalace/archive"},
        }
    }
    out = _render(merged)
    lines = out.splitlines()

    arc = next(ln for ln in lines if "Chat Session : Archiving" in ln)
    # archive ON -> its dir field shows on the Chat Session : Archiving line.
    assert ".brainpalace/archive" in arc

    vec = next(ln for ln in lines if "Chat Session : Vector Indexing" in ln)
    # vector OFF -> collapsed to the gate value, no embed detail (window/stride).
    assert vec.rstrip().endswith("off")
    assert "window" not in vec.lower()


def test_indexing_section_exposes_fields():
    from brainpalace_cli import config_fields as cf

    dps = {s.dotpath for s in cf.group_fields("indexing")}
    assert "indexing.exclude_patterns" in dps
    # chunk_size/overlap are NO LONGER config keys — advanced `index` flags only.
    assert "indexing.chunk_size" not in dps
    assert "indexing.chunk_overlap" not in dps
    assert ("indexing", "Indexing") in cf.GROUP_ORDER
