"""`brainpalace rehome` command."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.commands.rehome import rehome_command


def _mock_client(cm_return):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    for k, v in cm_return.items():
        getattr(client, k).return_value = v
    return client


def test_status_default_shows_quarantine():
    client = _mock_client(
        {
            "rehome_status": {
                "quarantined": True,
                "status": "failed",
                "reason": "nested move",
            }
        }
    )
    with patch("brainpalace_cli.commands.rehome.DocServeClient", return_value=client):
        r = CliRunner().invoke(rehome_command, [])
    assert r.exit_code == 0
    assert "nested move" in r.output
    client.rehome_status.assert_called_once()


def test_status_clear():
    client = _mock_client(
        {"rehome_status": {"quarantined": False, "status": None, "reason": None}}
    )
    with patch("brainpalace_cli.commands.rehome.DocServeClient", return_value=client):
        r = CliRunner().invoke(rehome_command, [])
    assert r.exit_code == 0
    assert "not" in r.output.lower() or "no rehome" in r.output.lower()


def test_resume_success():
    client = _mock_client(
        {
            "rehome_resume": {
                "quarantined": False,
                "status": "done",
                "resumed_workers": ["job_worker", "file_watcher_service"],
            }
        }
    )
    with patch("brainpalace_cli.commands.rehome.DocServeClient", return_value=client):
        r = CliRunner().invoke(rehome_command, ["--resume"])
    assert r.exit_code == 0
    assert "done" in r.output.lower()
    client.rehome_resume.assert_called_once()


def test_resume_nothing_pending_is_graceful():
    from brainpalace_cli.client.api_client import ServerError

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.rehome_resume.side_effect = ServerError(
        "x", status_code=409, detail="no pending rehome to resume"
    )
    with patch("brainpalace_cli.commands.rehome.DocServeClient", return_value=client):
        r = CliRunner().invoke(rehome_command, ["--resume"])
    assert r.exit_code == 0  # 409 = "nothing to do", not a failure
    assert "no pending" in r.output.lower() or "nothing" in r.output.lower()


def test_json_output():
    import json as _json

    client = _mock_client(
        {
            "rehome_status": {
                "quarantined": True,
                "status": "in_progress",
                "reason": None,
            }
        }
    )
    with patch("brainpalace_cli.commands.rehome.DocServeClient", return_value=client):
        r = CliRunner().invoke(rehome_command, ["--json"])
    assert r.exit_code == 0
    assert _json.loads(r.output)["status"] == "in_progress"
