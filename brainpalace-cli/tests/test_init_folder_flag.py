"""init -F/--folder: scoped initial index instead of project root (spec Item 2)."""

from unittest.mock import patch

from click.testing import CliRunner

from brainpalace_cli.commands.init import init_command


def _invoke(args, monkeypatch, tmp_path):
    # Wide terminal so Rich never soft-wraps long tmp_path lines mid-token,
    # keeping the rendered todo/done commands intact for substring asserts.
    monkeypatch.setenv("COLUMNS", "500")
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.get_xdg_config_dir",
        lambda: tmp_path / "xdg",
    )
    pc = "brainpalace_server.config.provider_config"
    with (
        patch(f"{pc}.load_provider_settings", return_value=object()),
        patch(f"{pc}.clear_settings_cache"),
        patch(f"{pc}.validate_provider_config", return_value=[]),
        patch(f"{pc}.has_critical_errors", return_value=False),
        patch("brainpalace_cli.commands.init._run_subcommand") as mock_run,
    ):
        mock_run.return_value = {"step": "start", "status": "ok"}
        result = CliRunner().invoke(init_command, args)
    return result, mock_run


def test_folder_flag_registers_only_given_folders(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    derived = proj / "data" / "derived"
    derived.mkdir(parents=True)
    result, mock_run = _invoke(
        ["--path", str(proj), "--start", "--yes", "-F", str(derived)],
        monkeypatch,
        tmp_path,
    )
    assert result.exit_code == 0, result.output
    folder_add_calls = [
        c.args[0]
        for c in mock_run.call_args_list
        if "folders" in c.args[0] and "add" in c.args[0]
    ]
    assert len(folder_add_calls) == 1
    assert str(derived) in folder_add_calls[0]
    assert not any(str(proj) == a for a in folder_add_calls[0])  # root NOT registered


def test_folder_flag_repeatable(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    a = proj / "a"
    a.mkdir()
    b = tmp_path / "outside"
    b.mkdir()
    result, mock_run = _invoke(
        ["--path", str(proj), "--start", "--yes", "-F", str(a), "-F", str(b)],
        monkeypatch,
        tmp_path,
    )
    assert result.exit_code == 0, result.output
    folder_add_calls = [
        c.args[0]
        for c in mock_run.call_args_list
        if "folders" in c.args[0] and "add" in c.args[0]
    ]
    assert len(folder_add_calls) == 2  # one per -F, external path OK


def test_folder_flag_external_path_passes_allow_external(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    result, mock_run = _invoke(
        ["--path", str(proj), "--start", "--yes", "-F", str(outside)],
        monkeypatch,
        tmp_path,
    )
    assert result.exit_code == 0, result.output
    folder_add_calls = [
        c.args[0]
        for c in mock_run.call_args_list
        if "folders" in c.args[0] and "add" in c.args[0]
    ]
    assert len(folder_add_calls) == 1
    assert "--allow-external" in folder_add_calls[0]


def test_folder_with_no_watch_is_usage_error(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    d = proj / "d"
    d.mkdir()
    result, _ = _invoke(
        ["--path", str(proj), "--no-watch", "-F", str(d)],
        monkeypatch,
        tmp_path,
    )
    assert result.exit_code != 0
    assert "--folder" in result.output or "-F" in result.output


def test_no_start_with_folders_prints_folders_add_todos(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    d = proj / "d"
    d.mkdir()
    result, mock_run = _invoke(
        ["--path", str(proj), "--no-start", "-F", str(d)],
        monkeypatch,
        tmp_path,
    )
    assert result.exit_code == 0, result.output
    assert f"folders add {d}" in result.output  # exact command todo
    # nothing started, nothing registered:
    assert not any("folders" in c.args[0] for c in mock_run.call_args_list)
