"""index_blocked surfaces in query --json and human output."""

import json
from types import SimpleNamespace
from typing import Any

from click.testing import CliRunner

from brainpalace_cli.commands import query as query_mod

_BLOCKED = {
    "job_id": "job_1",
    "folder_path": "/tmp/p",
    "estimated_tokens": 412000,
    "limit": 100000,
    "blocked_since": None,
}


def _fake_client(index_blocked: dict[str, Any] | None):
    class _FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *a: Any) -> None: ...
        def query(self, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                results=[],
                query_time_ms=1.0,
                total_results=0,
                compute=None,
                scan=None,
                index_blocked=index_blocked,
            )

    return _FakeClient


def test_json_carries_index_blocked(monkeypatch) -> None:
    monkeypatch.setattr(query_mod, "DocServeClient", _fake_client(_BLOCKED))
    result = CliRunner().invoke(query_mod.query_command, ["x", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["index_blocked"]["job_id"] == "job_1"


def test_json_omits_key_when_absent(monkeypatch) -> None:
    monkeypatch.setattr(query_mod, "DocServeClient", _fake_client(None))
    result = CliRunner().invoke(query_mod.query_command, ["x", "--json"])
    assert "index_blocked" not in json.loads(result.output)


def test_human_output_warns(monkeypatch) -> None:
    monkeypatch.setattr(query_mod, "DocServeClient", _fake_client(_BLOCKED))
    result = CliRunner().invoke(query_mod.query_command, ["x"])
    assert result.exit_code == 0, result.output
    assert "indexing paused" in result.output.lower()
    assert "job_1 --approve" in result.output
