"""--force-budget flag on index / folders add, threaded to the client."""

from types import SimpleNamespace
from typing import Any

from click.testing import CliRunner

from brainpalace_cli.commands import folders as folders_mod
from brainpalace_cli.commands import index as index_mod


class _FakeClient:
    last_kwargs: dict[str, Any] = {}

    def __init__(self, *a: Any, **k: Any) -> None: ...
    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *a: Any) -> None: ...
    def index(self, **kwargs: Any) -> SimpleNamespace:
        _FakeClient.last_kwargs = kwargs
        return SimpleNamespace(job_id="job_1", status="pending", message="ok")


def test_index_command_passes_force_budget(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(index_mod, "DocServeClient", _FakeClient)
    result = CliRunner().invoke(
        index_mod.index_command,
        [str(tmp_path), "--force-budget", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert _FakeClient.last_kwargs["force_budget"] is True


def test_folders_add_passes_force_budget(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(folders_mod, "DocServeClient", _FakeClient)
    result = CliRunner().invoke(
        folders_mod.folders_group,
        ["add", str(tmp_path), "--force-budget", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert _FakeClient.last_kwargs["force_budget"] is True


def test_folders_add_passes_domain_authority_force(tmp_path, monkeypatch) -> None:
    """folders add --domain/--authority/--force thread through to client.index()."""
    monkeypatch.setattr(folders_mod, "DocServeClient", _FakeClient)
    result = CliRunner().invoke(
        folders_mod.folders_group,
        [
            "add",
            str(tmp_path),
            "--domain",
            "home",
            "--authority",
            "reference",
            "--force",
            "--allow-external",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert _FakeClient.last_kwargs["domain"] == "home"
    assert _FakeClient.last_kwargs["authority"] == "reference"
    assert _FakeClient.last_kwargs["force_authority"] is True


def test_folders_add_domain_authority_default_none(tmp_path, monkeypatch) -> None:
    """Without the new flags, domain/authority/force_authority stay unset/False."""
    monkeypatch.setattr(folders_mod, "DocServeClient", _FakeClient)
    result = CliRunner().invoke(
        folders_mod.folders_group,
        ["add", str(tmp_path), "--json"],
    )
    assert result.exit_code == 0, result.output
    assert _FakeClient.last_kwargs["domain"] is None
    assert _FakeClient.last_kwargs["authority"] is None
    assert _FakeClient.last_kwargs["force_authority"] is False
