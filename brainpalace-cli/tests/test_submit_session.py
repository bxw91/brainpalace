"""Phase 060 — `brainpalace submit-session` CLI."""

from __future__ import annotations

import json

from click.testing import CliRunner

from brainpalace_cli.commands.sessions import submit_session_command


class _FakeClient:
    last_payload: dict | None = None

    def __init__(self, *a, **k) -> None:  # noqa: ANN002,ANN003
        pass

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *a) -> None:  # noqa: ANN002
        return None

    def submit_session_extract(self, payload):  # noqa: ANN001,ANN201
        _FakeClient.last_payload = payload
        return {
            "session_id": payload["session_id"],
            "summary_chunks": 1,
            "decision_chunks": len(payload.get("decisions", [])),
            "triplets_stored": 0,
            "digest_updated": False,
        }


def _patch(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("brainpalace_cli.commands.sessions.DocServeClient", _FakeClient)
    monkeypatch.setattr(
        "brainpalace_cli.commands.sessions.get_server_url",
        lambda: "http://127.0.0.1:8000",
    )


def test_submit_from_stdin(monkeypatch) -> None:  # noqa: ANN001
    _patch(monkeypatch)
    payload = {"session_id": "s1", "summary": "x", "decisions": [{"text": "d"}]}
    res = CliRunner().invoke(
        submit_session_command, ["--json", "-"], input=json.dumps(payload)
    )
    assert res.exit_code == 0, res.output
    assert _FakeClient.last_payload["session_id"] == "s1"
    assert "Stored session s1" in res.output


def test_session_id_arg_overrides_payload(monkeypatch) -> None:  # noqa: ANN001
    _patch(monkeypatch)
    payload = {"session_id": "old", "summary": "x"}
    res = CliRunner().invoke(
        submit_session_command,
        ["override-id", "--json", "-"],
        input=json.dumps(payload),
    )
    assert res.exit_code == 0, res.output
    assert _FakeClient.last_payload["session_id"] == "override-id"


def test_invalid_json_errors(monkeypatch) -> None:  # noqa: ANN001
    _patch(monkeypatch)
    res = CliRunner().invoke(submit_session_command, ["--json", "-"], input="not json")
    assert res.exit_code != 0
    assert "Invalid JSON" in res.output


def test_session_path_resolves_archive(tmp_path):
    from pathlib import Path  # noqa: F401

    from brainpalace_cli.commands.sessions import session_path_command

    arch = tmp_path / ".brainpalace" / "session_archive"
    arch.mkdir(parents=True)
    f = arch / "s1.jsonl"
    f.write_text("{}\n")
    (arch / "manifest.json").write_text(
        json.dumps(
            {"s1": {"session_id": "s1", "archive_path": str(f), "src_mtime": 1.0}}
        )
    )
    runner = CliRunner()
    result = runner.invoke(session_path_command, ["s1", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert result.output.strip() == str(f)


def test_session_path_unresolved_is_empty(tmp_path):
    from brainpalace_cli.commands.sessions import session_path_command

    (tmp_path / ".brainpalace").mkdir()
    runner = CliRunner()
    result = runner.invoke(session_path_command, ["nope", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert result.output.strip() == ""  # caller falls back to the live dir
