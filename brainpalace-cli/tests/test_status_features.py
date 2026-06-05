"""Phase 5.2 — `brainpalace status` renders the per-feature view."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.client.api_client import IndexingStatus
from brainpalace_cli.commands.status import status_command


def _status(features, graph_index=None):
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
    )


def _invoke(features, graph_index=None):
    health = MagicMock(status="healthy", message=None, version="1.0.0")
    runner = CliRunner()
    with patch("brainpalace_cli.commands.status.DocServeClient") as client_cls:
        inst = client_cls.return_value.__enter__.return_value
        inst.status.return_value = _status(features, graph_index=graph_index)
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


def test_status_renders_lsp_enabled():
    result = _invoke({"lsp": {"enabled": True, "languages": ["python", "go"]}})
    assert result.exit_code == 0, result.output
    out = result.output
    assert "LSP" in out
    assert "enabled" in out
    assert "python" in out and "go" in out


def test_status_renders_lsp_disabled():
    result = _invoke({"lsp": {"enabled": False, "languages": []}})
    assert result.exit_code == 0, result.output
    out = result.output
    assert "LSP" in out
    assert "disabled" in out
    assert "BRAINPALACE_LSP_LANGUAGES" in out


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
