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

    # Accept every prompt default: embedding/summarization provider+model,
    # graphrag mode, the three compute prompts, sessions/archive/git/rerank/lemma,
    # deployment + port, plus the two global-only dashboard prompts (17 total).
    result = CliRunner().invoke(config_group, ["wizard", "--global"], input="\n" * 17)

    assert result.exit_code == 0, result.output
    # The wizard writes a compute: block; the CLI-side schema validator must
    # recognise it so no "Continue anyway?" abort fires on a clean run.
    assert "Unknown top-level key" not in result.output
    written = xdg / "config.yaml"
    assert written.is_file(), result.output
    text = written.read_text()
    assert "embedding:" in text
    assert "summarization:" in text


def test_wizard_without_global_writes_to_cwd_project(
    tmp_path: Path, monkeypatch
) -> None:
    # No --global: writes a project-style .brainpalace/config.yaml under CWD.
    # 15 blank lines accept every prompt (incl. the three compute prompts).
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(config_group, ["wizard"], input="\n" * 15)
    assert result.exit_code == 0, result.output
    assert "Unknown top-level key" not in result.output
    assert (tmp_path / ".brainpalace" / "config.yaml").is_file(), result.output


def _run_wizard(tmp_path: Path, monkeypatch, args: list[str]):
    """Run the wizard in an isolated CWD, accepting every prompt default.

    15 blank lines cover every non-global prompt, including the three compute
    prompts. Asserts no schema "Unknown top-level key" abort fires so a future
    regression (e.g. compute dropped from VALID_TOP_LEVEL_KEYS) is caught.
    """
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(config_group, ["wizard", *args], input="\n" * 15)
    assert "Unknown top-level key" not in result.output, result.output
    return result


def test_chat_summarizer_plugin_wording(tmp_path: Path, monkeypatch) -> None:
    result = _run_wizard(tmp_path, monkeypatch, ["--chat-summarizer", "plugin"])
    assert result.exit_code == 0, result.output
    assert "for CODE only" in result.output
    assert "Code summarization provider" in result.output


def test_chat_summarizer_provider_wording(tmp_path: Path, monkeypatch) -> None:
    result = _run_wizard(tmp_path, monkeypatch, ["--chat-summarizer", "provider"])
    assert result.exit_code == 0, result.output
    # No-plugin: chat summaries are OFF by default (opt-in), NOT auto-billed.
    assert "Chat-session summarization is OFF" in result.output
    assert "SESSION_DISTILL_ENABLED=true" in result.output
    assert "Code summarization provider" in result.output


def test_chat_summarizer_auto_detects_plugin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "brainpalace_cli.commands.config.claude_plugin_installed", lambda: True
    )
    result = _run_wizard(tmp_path, monkeypatch, ["--chat-summarizer", "auto"])
    assert result.exit_code == 0, result.output
    assert "for CODE only" in result.output


def test_chat_summarizer_auto_detects_no_plugin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "brainpalace_cli.commands.config.claude_plugin_installed", lambda: False
    )
    result = _run_wizard(tmp_path, monkeypatch, ["--chat-summarizer", "auto"])
    assert result.exit_code == 0, result.output
    assert "Chat-session summarization is OFF" in result.output


def test_chat_summarizer_config_output_invariant(tmp_path: Path, monkeypatch) -> None:
    # The flag is wording-only: the written summarization block must be identical
    # across every --chat-summarizer value.
    written = {}
    for mode in ("plugin", "provider"):
        proj = tmp_path / mode
        proj.mkdir()
        result = _run_wizard(proj, monkeypatch, ["--chat-summarizer", mode])
        assert result.exit_code == 0, result.output
        written[mode] = (proj / ".brainpalace" / "config.yaml").read_text()
    assert written["plugin"] == written["provider"]
