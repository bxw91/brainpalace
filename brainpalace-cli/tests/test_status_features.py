"""Phase 5.2 — `brainpalace status` renders the per-feature view."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.client.api_client import IndexingStatus
from brainpalace_cli.commands.status import status_command


def _status(features):
    return IndexingStatus(
        total_documents=3,
        total_chunks=42,
        indexing_in_progress=False,
        current_job_id=None,
        progress_percent=0.0,
        last_indexed_at=None,
        indexed_folders=[],
        features=features,
    )


def _invoke(features):
    health = MagicMock(status="healthy", message=None, version="1.0.0")
    runner = CliRunner()
    with patch("brainpalace_cli.commands.status.DocServeClient") as client_cls:
        inst = client_cls.return_value.__enter__.return_value
        inst.status.return_value = _status(features)
        inst.health.return_value = health
        result = runner.invoke(status_command, [])
    return result


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
