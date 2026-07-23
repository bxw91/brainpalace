"""`brainpalace status` renders the shared server status report.

The per-feature row logic (file watcher, session memory, graph index, etc.)
now lives server-side in ``brainpalace_server.status_report`` (tested there,
see ``tests/unit/test_status_report.py``). The CLI's only job is to render
whatever ``rows``/``alerts`` the server sent — tone -> Rich color, alerts ->
Panels — so these tests exercise that rendering contract, not individual
feature wording.
"""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.client.api_client import IndexingStatus
from brainpalace_cli.commands.status import status_command


def _status(report=None, embedding_cache=None):
    return IndexingStatus(
        total_documents=3,
        total_chunks=42,
        indexing_in_progress=False,
        current_job_id=None,
        progress_percent=0.0,
        last_indexed_at=None,
        indexed_folders=[],
        embedding_cache=embedding_cache,
        report=report,
    )


def _invoke(report=None, embedding_cache=None, args=None):
    health = MagicMock(status="healthy", message=None, version="1.0.0")
    runner = CliRunner()
    with patch("brainpalace_cli.commands.status.DocServeClient") as client_cls:
        inst = client_cls.return_value.__enter__.return_value
        inst.status.return_value = _status(
            report=report, embedding_cache=embedding_cache
        )
        inst.health.return_value = health
        result = runner.invoke(status_command, args or [])
    return result


def test_status_renders_report_rows_with_tone_styling():
    report = {
        "rows": [
            {
                "key": "session_queue",
                "label": "Session Queue",
                "value": "330 pending",
                "tone": "warn",
            },
            {
                "key": "read_only",
                "label": "Read-Only",
                "value": "ON — provider calls disabled",
                "tone": "bad",
            },
            {
                "key": "indexing",
                "label": "Indexing",
                "value": "Idle",
                "tone": "good",
            },
        ],
        "alerts": [],
    }
    result = _invoke(report=report)
    assert result.exit_code == 0, result.output
    assert "Session Queue" in result.output
    assert "330 pending" in result.output
    assert "Read-Only" in result.output
    assert "ON — provider calls disabled" in result.output
    assert "Idle" in result.output


def test_status_renders_alerts_as_panels_with_action():
    report = {
        "rows": [],
        "alerts": [
            {
                "kind": "indexing_paused",
                "severity": "warn",
                "title": "Indexing paused",
                "lines": ["Indexing paused. Nothing was spent."],
                "action": "brainpalace jobs j1 --approve",
            },
            {
                "kind": "index_drift",
                "severity": "warn",
                "title": "Index drift",
                "lines": ["embedding model changed"],
            },
        ],
    }
    result = _invoke(report=report)
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Indexing paused" in out
    assert "brainpalace jobs j1 --approve" in out
    assert "Index drift" in out
    assert "embedding model changed" in out


def test_status_handles_missing_report_gracefully():
    # An older/minimal server (or a test double) with no `report` key at all —
    # the CLI must not crash; it just renders an empty table.
    result = _invoke(report=None)
    assert result.exit_code == 0, result.output


def test_status_verbose_shows_embedding_cache_extras():
    report = {"rows": [], "alerts": []}
    result = _invoke(
        report=report,
        embedding_cache={
            "entry_count": 10,
            "hit_rate": 0.5,
            "hits": 5,
            "misses": 5,
            "mem_entries": 3,
            "size_bytes": 2 * 1024 * 1024,
        },
        args=["--verbose"],
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Memory Entries" in out
    assert "Cache Size" in out
    assert "2.00 MB" in out


def test_status_json_includes_report():
    report = {
        "rows": [{"key": "server_version", "label": "Server Version", "value": "v"}],
        "alerts": [],
    }
    result = _invoke(report=report, args=["--json"])
    assert result.exit_code == 0, result.output
    import json

    data = json.loads(result.output)
    assert data["report"] == report
