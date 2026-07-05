"""Phase 3 Task 6 — absence rows through the CLI client and command."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from brainpalace_cli.client.api_client import AbsenceRow, DocServeClient


def test_parse_absence_rows() -> None:
    """DocServeClient.query() parses the server's `absence` field into AbsenceRow."""
    data = {
        "results": [],
        "query_time_ms": 3.2,
        "total_results": 1,
        "absence": [
            {
                "label": "walk",
                "present_in": "distance",
                "absent_from": "duration",
                "partition": "metric",
                "score": 0.0,
            }
        ],
    }
    with DocServeClient() as client:
        with patch.object(client, "_request", return_value=data):
            resp = client.query(
                "subjects with distance but not duration", mode="absence"
            )
    assert resp.absence == [
        AbsenceRow(
            label="walk",
            present_in="distance",
            absent_from="duration",
            partition="metric",
            score=0.0,
        )
    ]


def test_mode_choice_accepts_absence() -> None:
    from brainpalace_cli.commands.query import query_command

    runner = CliRunner()
    # --help never contacts a server; asserts the choice list includes absence.
    out = runner.invoke(query_command, ["--help"]).output
    assert "absence" in out
