"""Hard-off session-recall gating in the query path.

When a session feature is OFF, its chunks must be unreachable via search:
``_build_where_clause`` excludes them with ``$nin`` (vector/hybrid) and
``hidden_session_source_types`` drives the channel-agnostic post-filter that
also covers bm25. Keyless — no embeddings or Chroma.
"""

from __future__ import annotations

from brainpalace_server.services import query_service as qs
from brainpalace_server.services.query_service import (
    QueryService,
    hidden_session_source_types,
)


def _patch_flags(monkeypatch, *, vector: bool, summarization: bool):
    monkeypatch.setattr(
        "brainpalace_server.config.session_config.session_recall_flags",
        lambda *a, **k: (vector, summarization),
    )


def test_hidden_types_both_off(monkeypatch):
    _patch_flags(monkeypatch, vector=False, summarization=False)
    assert hidden_session_source_types() == {
        "session_turn",
        "session_summary",
        "session_decision",
    }


def test_hidden_types_vector_off_only(monkeypatch):
    _patch_flags(monkeypatch, vector=False, summarization=True)
    assert hidden_session_source_types() == {"session_turn"}


def test_hidden_types_summarization_off_only(monkeypatch):
    _patch_flags(monkeypatch, vector=True, summarization=False)
    assert hidden_session_source_types() == {"session_summary", "session_decision"}


def test_hidden_types_all_on(monkeypatch):
    _patch_flags(monkeypatch, vector=True, summarization=True)
    assert hidden_session_source_types() == set()


def test_where_clause_excludes_hidden_when_off(monkeypatch):
    _patch_flags(monkeypatch, vector=False, summarization=True)
    svc = QueryService.__new__(QueryService)
    where = svc._build_where_clause(None, None)
    assert where == {"source_type": {"$nin": ["session_turn"]}}


def test_where_clause_combines_with_source_types(monkeypatch):
    _patch_flags(monkeypatch, vector=False, summarization=False)
    svc = QueryService.__new__(QueryService)
    where = svc._build_where_clause(["doc"], None)
    assert "$and" in where
    assert {"source_type": "doc"} in where["$and"]
    assert {
        "source_type": {"$nin": ["session_decision", "session_summary", "session_turn"]}
    } in where["$and"]


def test_where_clause_none_when_all_on(monkeypatch):
    _patch_flags(monkeypatch, vector=True, summarization=True)
    svc = QueryService.__new__(QueryService)
    assert svc._build_where_clause(None, None) is None


def test_fail_open_on_flag_error(monkeypatch):
    # session_recall_flags itself fails open; emulate a clean (True, True).
    monkeypatch.setattr(qs, "hidden_session_source_types", lambda: set(), raising=True)
    assert qs.hidden_session_source_types() == set()
