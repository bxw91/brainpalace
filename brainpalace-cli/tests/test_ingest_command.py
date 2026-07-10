"""brainpalace ingest — CLI wrapper over POST/DELETE /ingest/text."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.commands.ingest import ingest_command


def _invoke(args, input=None, response=None):
    client = MagicMock()
    client.__enter__ = lambda s: s
    client.__exit__ = lambda s, *a: False
    client.ingest_text.return_value = response or {
        "chunks_new": 1,
        "chunks_kept": 0,
        "chunks_deleted": 0,
        "chunk_ids": ["ing_1"],
        "source_ids": ["s1"],
    }
    client.ingest_delete.return_value = {"chunks_deleted": 2}
    client.ingest_records.return_value = {"records": 1}
    client.ingest_references.return_value = {"references": 1}
    with patch("brainpalace_cli.commands.ingest.DocServeClient", return_value=client):
        result = CliRunner().invoke(ingest_command, args, input=input)
    return result, client


def test_ingest_from_stdin():
    result, client = _invoke(
        [
            "-",
            "--domain",
            "home",
            "--source",
            "scanner",
            "--source-id",
            "s1",
            "--language",
            "hr",
            "--json",
        ],
        input="racun za struju 420 kn",
    )
    assert result.exit_code == 0, result.output
    payload = client.ingest_text.call_args.kwargs
    assert payload["items"][0]["text"].startswith("racun")
    assert payload["items"][0]["source_id"] == "s1"
    assert payload["language"] == "hr"
    assert json.loads(result.output)["chunks_new"] == 1


def test_ingest_metadata_pairs():
    result, client = _invoke(
        [
            "-",
            "--domain",
            "home",
            "--source",
            "scanner",
            "--source-id",
            "s1",
            "--metadata",
            "page=2",
            "--metadata",
            "complete=false",
        ],
        input="tekst",
    )
    assert result.exit_code == 0, result.output
    items = client.ingest_text.call_args.kwargs["items"]
    assert items[0]["metadata"] == {"page": "2", "complete": "false"}


def test_ingest_delete():
    result, client = _invoke(["--delete", "--source-id", "s1", "--json"])
    assert result.exit_code == 0, result.output
    client.ingest_delete.assert_called_once_with("s1")


def test_ingest_requires_provenance():
    result, _ = _invoke(["-"], input="x")
    assert result.exit_code != 0  # --domain/--source/--source-id required


def test_ingest_record_subcommand():
    result, client = _invoke(
        [
            "record",
            "--subject",
            "electricity",
            "--metric",
            "kwh",
            "--value",
            "420",
            "--domain",
            "home",
            "--source",
            "meter",
            "--source-id",
            "bill-1",
            "--json",
        ]
    )
    assert result.exit_code == 0, result.output
    item = client.ingest_records.call_args.kwargs["items"][0]
    assert item["subject"] == "electricity"
    assert item["value"] == 420.0
    assert item["confidence"] == 1.0
    assert json.loads(result.output)["records"] == 1


def test_ingest_reference_subcommand():
    result, client = _invoke(
        [
            "reference",
            "--pointer",
            "file:///scan/bill-1.pdf",
            "--summary",
            "electricity bill",
            "--domain",
            "home",
            "--source",
            "scanner",
            "--source-id",
            "bill-1",
            "--sensitivity",
            "private",
            "--json",
        ]
    )
    assert result.exit_code == 0, result.output
    kwargs = client.ingest_references.call_args.kwargs
    assert kwargs["items"][0]["pointer"] == "file:///scan/bill-1.pdf"
    assert kwargs["sensitivity"] == "private"
    assert json.loads(result.output)["references"] == 1
