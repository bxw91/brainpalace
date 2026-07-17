"""jobs --all flag (Fix 4 / A7): reveal no-op completed jobs, and the
"N no-op runs hidden" hint when they're not shown."""

from typing import Any

from click.testing import CliRunner

from brainpalace_cli.commands import jobs as jobs_mod


class _FakeClient:
    def __init__(self, *a: Any, **k: Any) -> None: ...
    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *a: Any) -> None: ...

    def list_jobs_page(
        self, limit: int = 20, offset: int = 0, all_: bool = False
    ) -> dict[str, Any]:
        self.last_all = all_
        jobs = [{"id": "job_real", "status": "done", "chunks_added": 5}]
        if all_:
            jobs.append({"id": "job_noop", "status": "done", "chunks_added": 0})
            return {"jobs": jobs, "total": 2, "noop_hidden": 0}
        return {"jobs": jobs, "total": 2, "noop_hidden": 1}


def test_jobs_default_hides_noop_and_shows_hint(monkeypatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(jobs_mod, "DocServeClient", lambda *a, **k: fake)
    result = CliRunner().invoke(jobs_mod.jobs_command, [])
    assert result.exit_code == 0, result.output
    assert "job_real" in result.output
    assert "job_noop" not in result.output
    assert "no-op" in result.output.lower()
    assert "--all" in result.output


def test_jobs_all_flag_reveals_noop_and_passes_all_true(monkeypatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(jobs_mod, "DocServeClient", lambda *a, **k: fake)
    result = CliRunner().invoke(jobs_mod.jobs_command, ["--all"])
    assert result.exit_code == 0, result.output
    assert fake.last_all is True
    assert "job_noop" in result.output
    # No hint once no-op jobs are already shown.
    assert "hidden" not in result.output.lower()


def test_jobs_json_output_unaffected_by_hint(monkeypatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(jobs_mod, "DocServeClient", lambda *a, **k: fake)
    result = CliRunner().invoke(jobs_mod.jobs_command, ["--json"])
    assert result.exit_code == 0, result.output
    import json

    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data == [{"id": "job_real", "status": "done", "chunks_added": 5}]
