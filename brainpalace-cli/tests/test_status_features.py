"""Phase 5.2 — `brainpalace status` renders the per-feature view."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.client.api_client import IndexingStatus
from brainpalace_cli.commands.status import status_command


def _status(features, graph_index=None, text_ingest=None):
    return IndexingStatus(
        total_documents=3,
        total_chunks=42,
        indexing_in_progress=False,
        current_job_id=None,
        progress_percent=0.0,
        last_indexed_at=None,
        indexed_folders=[],
        features=features,
        graph_index=graph_index,
        text_ingest=text_ingest,
    )


def _invoke(features, graph_index=None, text_ingest=None):
    health = MagicMock(status="healthy", message=None, version="1.0.0")
    runner = CliRunner()
    with patch("brainpalace_cli.commands.status.DocServeClient") as client_cls:
        inst = client_cls.return_value.__enter__.return_value
        inst.status.return_value = _status(
            features, graph_index=graph_index, text_ingest=text_ingest
        )
        inst.health.return_value = health
        result = runner.invoke(status_command, [])
    return result


def test_status_renders_text_ingest_when_present():
    result = _invoke(
        {"doc_indexing": {"active": True, "total_chunks": 42, "total_documents": 3}},
        text_ingest={"chunks": 7},
    )
    assert result.exit_code == 0, result.output
    assert "Text Ingest" in result.output
    assert "7" in result.output


def test_status_hides_text_ingest_when_zero():
    result = _invoke(
        {"doc_indexing": {"active": True, "total_chunks": 42, "total_documents": 3}},
        text_ingest={"chunks": 0},
    )
    assert result.exit_code == 0, result.output
    assert "Text Ingest" not in result.output


def test_status_renders_session_memory_on():
    result = _invoke(
        {
            "doc_indexing": {"active": True, "total_chunks": 42, "total_documents": 3},
            "file_watcher": {"enabled": True, "watched_folders": 1},
            "session_memory": {
                "enabled": True,
                "watcher_running": True,
                "session_chunks": 42,
                "curated_memories": 5,
            },
            "graph_index": {"enabled": False},
        }
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Session Memory" in out
    assert "42" in out and "5" in out
    assert "watching" in out


def test_status_renders_memory_cap_usage():
    result = _invoke(
        {
            "doc_indexing": {"active": True, "total_chunks": 42, "total_documents": 3},
            "file_watcher": {"enabled": True, "watched_folders": 1},
            "session_memory": {
                "enabled": True,
                "watcher_running": True,
                "session_chunks": 42,
                "curated_memories": 5,
                "memory_char_count": 1200,
                "memory_char_cap": 8000,
                "memory_cap_pressure": None,
            },
        }
    )
    assert result.exit_code == 0, result.output
    # Rich wraps long cell text across lines (and interleaves table borders), so
    # the used/cap figure and its unit label may not be contiguous. Assert the
    # load-bearing figure and the unit label independently.
    assert "1200/8000" in result.output
    assert "chars" in result.output


def test_status_renders_memory_cap_pressure_warning():
    result = _invoke(
        {
            "doc_indexing": {"active": True, "total_chunks": 42, "total_documents": 3},
            "file_watcher": {"enabled": True, "watched_folders": 1},
            "session_memory": {
                "enabled": True,
                "watcher_running": True,
                "session_chunks": 42,
                "curated_memories": 5,
                "memory_char_count": 8000,
                "memory_char_cap": 8000,
                "memory_cap_pressure": {
                    "at": "2026-07-09T00:00:00+00:00",
                    "skipped": 3,
                },
            },
        }
    )
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "cap pressure" in flat
    assert "3 promotions skipped" in flat


def test_status_renders_session_memory_off():
    result = _invoke(
        {
            "file_watcher": {"enabled": True, "watched_folders": 1},
            "session_memory": {
                "enabled": False,
                "watcher_running": False,
                "session_chunks": 0,
                "curated_memories": 0,
            },
        }
    )
    assert result.exit_code == 0, result.output
    assert "Session Memory" in result.output
    assert "init --sessions" in result.output


def test_status_file_watcher_zero_folders_is_clear():
    result = _invoke({"file_watcher": {"enabled": True, "watched_folders": 0}})
    assert result.exit_code == 0, result.output
    assert "0 folders" in result.output


def test_status_renders_session_summarization_off():
    # Summarization is a separate capability from embedding (Session Memory)
    # and raw archive — it must be shown even when off, not hidden.
    result = _invoke(
        {
            "session_extraction": {
                "mode": "off",
                "summarized_pct": 0.0,
                "summarized_sessions": 0,
                "total_sessions": 30,
            },
        }
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Summarization" in out
    assert "off" in out


def test_status_renders_lsp_enabled():
    result = _invoke({"lsp": {"enabled": True, "active": ["python", "go"]}})
    assert result.exit_code == 0, result.output
    out = result.output
    assert "LSP" in out
    assert "active" in out
    assert "python" in out and "go" in out


def test_status_renders_lsp_disabled():
    result = _invoke({"lsp": {"enabled": False, "active": [], "detected": []}})
    assert result.exit_code == 0, result.output
    out = result.output
    assert "LSP" in out
    assert "not found" in out
    assert "pyright" in out


def test_status_lsp_configured_but_missing_points_to_install():
    # Enabled for python (configured) but no server binary detected: name the
    # language and point at `brainpalace lsp install` (read-only nudge, no install).
    result = _invoke(
        {
            "lsp": {
                "enabled": False,
                "mode": "auto",
                "active": [],
                "detected": [],
                "configured": ["python"],
                "via_env": False,
            }
        }
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "LSP" in out
    assert "python" in out
    assert "lsp install" in out


def test_status_renders_git_index_on():
    result = _invoke({"git_index": {"enabled": True, "commit_count": 1234}})
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Git Index" in out
    assert "1,234" in out


def test_status_renders_git_index_off():
    result = _invoke({"git_index": {"enabled": False, "commit_count": 0}})
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Git Index" in out
    assert "off" in out
    assert "--git-history" in out


def test_status_graph_store_type_sqlite_temporal():
    result = _invoke(
        {},
        graph_index={
            "enabled": True,
            "entity_count": 10,
            "relationship_count": 5,
            "store_type": "sqlite",
        },
    )
    assert result.exit_code == 0, result.output
    assert "sqlite, temporal" in result.output


def test_status_graph_store_type_simple_no_temporal():
    result = _invoke(
        {},
        graph_index={
            "enabled": True,
            "entity_count": 10,
            "relationship_count": 5,
            "store_type": "simple",
        },
    )
    assert result.exit_code == 0, result.output
    assert "no temporal validity" in result.output


def test_status_renders_session_summarization_on():
    result = _invoke(
        {
            "session_extraction": {
                "mode": "subagent",
                "summarized_pct": 40.0,
                "summarized_sessions": 12,
                "total_sessions": 30,
            },
        }
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Summarization" in out
    assert "subagent" in out


# ---------------------------------------------------------------------------
# Task 6 — render_doc_graph_extraction_row (pure renderer, M1 wording)
# ---------------------------------------------------------------------------


def test_render_doc_graph_extraction_subagent_with_pending():
    from brainpalace_cli.commands.status import render_doc_graph_extraction_row

    row = render_doc_graph_extraction_row(
        {"state": "subagent", "pending": 7, "ungraphed": False, "provider": None}
    )
    assert "on (subagent)" in row
    assert "7" in row


def test_render_doc_graph_extraction_off_with_ungraphed():
    # M1: off + pending → "un-graphed", NOT "pending"
    from brainpalace_cli.commands.status import render_doc_graph_extraction_row

    row = render_doc_graph_extraction_row(
        {"state": "off", "pending": 3, "ungraphed": True, "provider": None}
    )
    assert "off" in row
    assert "un-graphed" in row
    assert "pending" not in row.lower().replace("un-graphed", "")


def test_render_doc_graph_extraction_off_no_pending():
    from brainpalace_cli.commands.status import render_doc_graph_extraction_row

    row = render_doc_graph_extraction_row(
        {"state": "off", "pending": 0, "ungraphed": False, "provider": None}
    )
    assert "off" in row


def test_render_doc_graph_extraction_provider():
    from brainpalace_cli.commands.status import render_doc_graph_extraction_row

    row = render_doc_graph_extraction_row(
        {
            "state": "provider",
            "pending": 2,
            "ungraphed": False,
            "provider": "anthropic:claude-haiku-4-5",
        }
    )
    assert "on (provider" in row
    assert "anthropic:claude-haiku-4-5" in row


def test_render_doc_graph_extraction_unavailable():
    from brainpalace_cli.commands.status import render_doc_graph_extraction_row

    row = render_doc_graph_extraction_row(
        {"state": "unavailable", "pending": 0, "ungraphed": False, "provider": None}
    )
    assert "unavailable" in row.lower()


def test_status_renders_doc_graph_extraction_row():
    # Integration: the row appears in the CLI output table
    result = _invoke(
        {
            "doc_graph_extraction": {
                "state": "subagent",
                "pending": 4,
                "ungraphed": False,
                "mode": "subagent",
                "graphrag_enabled": True,
                "provider": None,
            },
        }
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Doc Graph" in out
    assert "subagent" in out


# ---------------------------------------------------------------------------
# Session Queue (to-summarize backlog) row
# ---------------------------------------------------------------------------


def test_render_session_queue_with_backlog():
    from brainpalace_cli.commands.status import render_session_queue_row

    row = render_session_queue_row({"pending_summarization": 3})
    assert "3 pending" in row
    assert "subagent/auto" in row


def test_render_session_queue_empty():
    from brainpalace_cli.commands.status import render_session_queue_row

    assert "empty" in render_session_queue_row({"pending_summarization": 0})
    assert "empty" in render_session_queue_row({})  # missing key → 0


def test_status_renders_session_queue_row():
    result = _invoke(
        {
            "session_archive": {
                "enabled": True,
                "archived_files": 5,
                "archived_bytes": 0,
                "retain_days": 0,
                "pending_summarization": 3,
            },
        }
    )
    assert result.exit_code == 0, result.output
    assert "Session Queue" in result.output


def test_status_renders_detected_session_tools():
    result = _invoke(
        {
            "doc_indexing": {
                "active": True,
                "total_chunks": 42,
                "total_documents": 3,
            },
            "session_archive": {
                "enabled": True,
                "archived_files": 2,
                "archived_bytes": 0,
                "retain_days": 0,
                "pending_summarization": 0,
                "tools": ["claude-code", "codex"],
            },
        }
    )
    assert result.exit_code == 0, result.output
    assert "Session Tools" in result.output
    assert "claude-code, codex" in result.output


def test_status_session_tools_empty_is_explicit():
    result = _invoke(
        {
            "doc_indexing": {
                "active": True,
                "total_chunks": 42,
                "total_documents": 3,
            },
            "session_archive": {
                "enabled": True,
                "archived_files": 0,
                "archived_bytes": 0,
                "retain_days": 0,
                "pending_summarization": 0,
                "tools": [],
            },
        }
    )
    assert result.exit_code == 0, result.output
    assert "Session Tools" in result.output
    assert "none detected" in result.output
