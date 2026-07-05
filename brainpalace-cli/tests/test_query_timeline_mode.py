"""Phase 4 Task 6 — timeline rows through the CLI client and command."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from brainpalace_cli.client.api_client import DocServeClient, TimelineRow


def test_parse_timeline_rows() -> None:
    """DocServeClient.query() parses the server's `timeline` field."""
    data = {
        "results": [],
        "query_time_ms": 4.1,
        "total_results": 1,
        "timeline": [
            {
                "subject": "use in-memory cache",
                "predicate": "superseded-by",
                "object": "use Redis cache",
                "valid_from": "2026-03-01T00:00:00",
                "valid_until": None,
                "valid": True,
                "score": 0.0,
            }
        ],
    }
    with DocServeClient() as client:
        with patch.object(client, "_request", return_value=data):
            resp = client.query("how did the cache evolve", mode="timeline")
    assert resp.timeline == [
        TimelineRow(
            subject="use in-memory cache",
            predicate="superseded-by",
            object="use Redis cache",
            valid_from="2026-03-01T00:00:00",
            valid_until=None,
            valid=True,
            score=0.0,
        )
    ]


def test_mode_choice_accepts_timeline() -> None:
    from brainpalace_cli.commands.query import query_command

    runner = CliRunner()
    out = runner.invoke(query_command, ["--help"]).output
    assert "timeline" in out
