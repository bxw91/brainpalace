"""Fix 4 (A7) — DocServeClient threads the no-op-hidden reveal hatch through.

`list_jobs_page` returns the full JobListResponse payload (jobs + counts +
noop_hidden); `list_jobs` stays a back-compat wrapper returning just the jobs
list, unchanged for existing callers (MCP tool, etc).
"""

from unittest.mock import MagicMock, patch

from brainpalace_cli.client import DocServeClient


@patch("httpx.Client.request")
def test_list_jobs_page_default_omits_all_param(mock_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "jobs": [{"id": "job_1"}],
        "total": 1,
        "noop_hidden": 3,
    }
    mock_request.return_value = mock_response

    with DocServeClient() as client:
        payload = client.list_jobs_page(limit=20)

    assert payload["noop_hidden"] == 3
    assert payload["jobs"] == [{"id": "job_1"}]
    _, kwargs = mock_request.call_args
    assert kwargs["params"].get("all") in (None, False)


@patch("httpx.Client.request")
def test_list_jobs_page_all_true_sends_all_param(mock_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"jobs": [], "total": 0, "noop_hidden": 0}
    mock_request.return_value = mock_response

    with DocServeClient() as client:
        client.list_jobs_page(limit=20, all_=True)

    _, kwargs = mock_request.call_args
    assert kwargs["params"]["all"] == 1


@patch("httpx.Client.request")
def test_list_jobs_backcompat_returns_jobs_list_only(mock_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "jobs": [{"id": "job_1"}, {"id": "job_2"}],
        "total": 2,
        "noop_hidden": 0,
    }
    mock_request.return_value = mock_response

    with DocServeClient() as client:
        jobs = client.list_jobs(limit=20)

    assert jobs == [{"id": "job_1"}, {"id": "job_2"}]
