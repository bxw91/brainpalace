"""brainpalace entities — CLI wrapper over /entities/*. Mirrors
tests/test_ingest_command.py: a MagicMock client, and the --json failure
contract (error object, non-zero exit, no results key)."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.client import ServerError
from brainpalace_cli.commands.entities import entities_group


def _invoke(args, configure=None):
    client = MagicMock()
    client.__enter__ = lambda s: s
    client.__exit__ = lambda s, *a: False
    if configure:
        configure(client)
    with patch("brainpalace_cli.commands.entities.DocServeClient", return_value=client):
        result = CliRunner().invoke(entities_group, args)
    return result, client


def test_person_upsert_json():
    result, client = _invoke(
        ["person", "--domain", "home", "--name", "Ana", "--json"],
        configure=lambda c: setattr(
            c.entities_person, "return_value", {"person_id": "p1"}
        ),
    )
    assert result.exit_code == 0, result.output
    body = client.entities_person.call_args.args[0]
    assert body["domain"] == "home" and body["name"] == "Ana"
    assert json.loads(result.output)["person_id"] == "p1"


def test_resolve_passes_scope_and_at():
    result, client = _invoke(
        [
            "resolve",
            "--surface",
            "Mama",
            "--scope",
            "spk",
            "--at",
            "2026-07-09T00:00:00Z",
            "--json",
        ],
        configure=lambda c: setattr(
            c.entities_resolve, "return_value", {"candidates": [{"person_id": "p1"}]}
        ),
    )
    assert result.exit_code == 0, result.output
    kwargs = client.entities_resolve.call_args.kwargs
    assert kwargs["surface"] == "Mama" and kwargs["scope"] == "spk"
    assert json.loads(result.output)["candidates"][0]["person_id"] == "p1"


def test_link_omits_person_id_when_unresolved():
    result, client = _invoke(
        [
            "link",
            "--ref",
            "msg_1#0",
            "--ref-kind",
            "span",
            "--role",
            "mentioned",
            "--method",
            "alias_match",
            "--at",
            "2026-07-09T00:00:00Z",
            "--surface",
            "Mama",
        ],
        configure=lambda c: setattr(c.entities_link, "return_value", {"link_id": "l1"}),
    )
    assert result.exit_code == 0, result.output
    body = client.entities_link.call_args.args[0]
    assert "person_id" not in body  # unresolved
    assert body["surface"] == "Mama"


def test_json_failure_contract():
    def boom(c):
        c.entities_backfill.side_effect = ServerError(
            "Server returned 503", status_code=503, detail="no store"
        )

    result, _ = _invoke(["backfill", "--json"], configure=boom)
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["error"] and "results" not in payload
