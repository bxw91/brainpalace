"""DocServeClient: approve_job, force_budget body key, index_blocked parsing."""

from typing import Any

from brainpalace_cli.client import DocServeClient


def _capture(client: DocServeClient, response: dict[str, Any]) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    def fake_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        calls.update(method=method, path=path, **kwargs)
        return response

    client._request = fake_request  # type: ignore[method-assign]
    return calls


def test_approve_job_posts_to_approve_endpoint() -> None:
    client = DocServeClient(base_url="http://127.0.0.1:1")
    calls = _capture(client, {"job_id": "job_1", "status": "pending"})
    out = client.approve_job("job_1")
    assert calls["method"] == "POST"
    assert calls["path"] == "/index/jobs/job_1/approve"
    assert out["status"] == "pending"


def test_index_sends_force_budget() -> None:
    client = DocServeClient(base_url="http://127.0.0.1:1")
    calls = _capture(client, {"job_id": "job_1", "status": "pending", "message": "ok"})
    client.index(folder_path="/tmp/p", force_budget=True)
    assert calls["json"]["force_budget"] is True


def test_query_parses_index_blocked() -> None:
    client = DocServeClient(base_url="http://127.0.0.1:1")
    blocked = {
        "job_id": "job_1",
        "folder_path": "/tmp/p",
        "estimated_tokens": 5,
        "limit": 1,
        "blocked_since": None,
    }
    _capture(
        client,
        {
            "results": [],
            "query_time_ms": 1.0,
            "total_results": 0,
            "index_blocked": blocked,
        },
    )
    resp = client.query(query_text="x")
    assert resp.index_blocked == blocked


def test_query_index_blocked_defaults_none() -> None:
    client = DocServeClient(base_url="http://127.0.0.1:1")
    _capture(client, {"results": [], "query_time_ms": 1.0, "total_results": 0})
    assert client.query(query_text="x").index_blocked is None
