"""`brainpalace config wizard --global` writes to the XDG global config."""

from pathlib import Path

from click.testing import CliRunner

from brainpalace_cli.commands.config import config_group


def test_wizard_global_writes_to_xdg(tmp_path: Path, monkeypatch) -> None:
    xdg = tmp_path / "xdg"
    # Both the command module and any xdg_paths lookup should point here.
    monkeypatch.setattr(
        "brainpalace_cli.commands.config.get_xdg_config_dir", lambda: xdg
    )

    # Accept every prompt default (openai/anthropic/graphrag=3/localhost/port).
    result = CliRunner().invoke(config_group, ["wizard", "--global"], input="\n" * 12)

    assert result.exit_code == 0, result.output
    written = xdg / "config.yaml"
    assert written.is_file(), result.output
    text = written.read_text()
    assert "embedding:" in text
    assert "summarization:" in text


def test_wizard_without_global_writes_to_cwd_project(
    tmp_path: Path, monkeypatch
) -> None:
    # No --global: writes a project-style .brainpalace/config.yaml under CWD.
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(config_group, ["wizard"], input="\n" * 12)
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".brainpalace" / "config.yaml").is_file(), result.output
