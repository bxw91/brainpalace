"""``query --also <path-or-url>`` cross-instance fan-out (household M1)."""

import json
from types import SimpleNamespace
from typing import Any

from click.testing import CliRunner

from brainpalace_cli.client.api_client import ConnectionError as ClientConnectionError
from brainpalace_cli.commands import query as query_mod


def _qr(chunk_id: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(
        text=f"text-{chunk_id}",
        source=f"src-{chunk_id}",
        score=score,
        chunk_id=chunk_id,
        metadata={},
        vector_score=None,
        bm25_score=None,
    )


def _response(results: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        results=results,
        query_time_ms=1.0,
        total_results=len(results),
        compute=None,
        scan=None,
        absence=None,
        timeline=None,
        index_blocked=None,
    )


RESULTS_BY_URL = {
    "http://127.0.0.1:8000": [_qr("local-1", 0.9), _qr("local-2", 0.8)],
    "http://sibling:9000": [_qr("sib-1", 0.7), _qr("sib-2", 0.6)],
}

constructed_urls: list[str] = []


def _fake_client_factory(raise_for: set[str] | None = None):
    raise_for = raise_for or set()

    class _FakeClient:
        def __init__(self, base_url: str = "", **kwargs: Any) -> None:
            self.base_url = base_url
            constructed_urls.append(base_url)

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *a: Any) -> None: ...

        def query(self, **kwargs: Any) -> SimpleNamespace:
            if self.base_url in raise_for:
                raise ClientConnectionError(f"cannot reach {self.base_url}")
            return _response(RESULTS_BY_URL.get(self.base_url, []))

    return _FakeClient


def test_two_clients_constructed_with_different_base_urls(monkeypatch) -> None:
    constructed_urls.clear()
    monkeypatch.setattr(query_mod, "DocServeClient", _fake_client_factory())
    monkeypatch.setattr(query_mod, "_get_default_url", lambda: "http://127.0.0.1:8000")
    result = CliRunner().invoke(
        query_mod.query_command,
        ["x", "--also", "http://sibling:9000", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert set(constructed_urls) == {"http://127.0.0.1:8000", "http://sibling:9000"}


def test_merged_json_output_carries_both_instance_tags(monkeypatch) -> None:
    constructed_urls.clear()
    monkeypatch.setattr(query_mod, "DocServeClient", _fake_client_factory())
    monkeypatch.setattr(query_mod, "_get_default_url", lambda: "http://127.0.0.1:8000")
    result = CliRunner().invoke(
        query_mod.query_command,
        ["x", "--also", "http://sibling:9000", "--json", "--top-k", "10"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    instances = {r["instance"] for r in payload["results"]}
    assert instances == {"local", "http://sibling:9000"}


def test_unreachable_sibling_warns_and_local_still_renders(monkeypatch) -> None:
    constructed_urls.clear()
    monkeypatch.setattr(
        query_mod,
        "DocServeClient",
        _fake_client_factory(raise_for={"http://sibling:9000"}),
    )
    monkeypatch.setattr(query_mod, "_get_default_url", lambda: "http://127.0.0.1:8000")
    result = CliRunner().invoke(
        query_mod.query_command,
        ["x", "--also", "http://sibling:9000", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert "unreachable" in result.stderr.lower()
    payload = json.loads(result.stdout)
    instances = {r["instance"] for r in payload["results"]}
    assert instances == {"local"}
    assert payload["results"], "local results should still render"
