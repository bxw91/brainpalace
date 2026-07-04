"""jobs --approve flag + blocked status styling."""

from typing import Any

from click.testing import CliRunner

from brainpalace_cli.commands import jobs as jobs_mod


def test_blocked_status_has_style() -> None:
    assert jobs_mod._get_status_style("blocked") != jobs_mod._get_status_style("???")


def test_jobs_approve_calls_client(monkeypatch) -> None:
    approved: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *a: Any) -> None: ...
        def approve_job(self, job_id: str) -> dict[str, Any]:
            approved["job_id"] = job_id
            return {"job_id": job_id, "status": "pending", "message": "ok"}

    monkeypatch.setattr(jobs_mod, "DocServeClient", _FakeClient)
    result = CliRunner().invoke(jobs_mod.jobs_command, ["job_1", "--approve", "--json"])
    assert result.exit_code == 0, result.output
    assert approved["job_id"] == "job_1"
    assert '"pending"' in result.output
