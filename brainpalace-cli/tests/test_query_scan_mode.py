"""Phase 2 Task 7 — scan rows through the CLI client and command."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from brainpalace_cli.client.api_client import DocServeClient, ScanRow


def test_parse_scan_rows() -> None:
    """DocServeClient.query() parses the server's `scan` field into ScanRow."""
    data = {
        "results": [],
        "query_time_ms": 3.2,
        "total_results": 1,
        "scan": [
            {
                "label": "2026-W03",
                "value": 3.0,
                "term": "foobar",
                "group": "2026-W03",
                "score": 1.0,
            }
        ],
    }
    with DocServeClient() as client:
        with patch.object(client, "_request", return_value=data):
            resp = client.query("which week did I mention foobar most", mode="scan")
    assert resp.scan == [
        ScanRow(label="2026-W03", value=3.0, term="foobar", group="2026-W03", score=1.0)
    ]


def test_mode_choice_accepts_scan() -> None:
    from brainpalace_cli.commands.query import query_command

    runner = CliRunner()
    # --help never contacts a server; asserts the choice list includes scan.
    out = runner.invoke(query_command, ["--help"]).output
    assert "scan" in out
