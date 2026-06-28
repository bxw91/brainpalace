"""Tests for init --global: edits XDG config layer."""

import json

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands.init import init_command


def _patch_xdg(monkeypatch, tmp_path):
    # Patch the ROOT resolver only; global_config_path() derives from it (one mock).
    monkeypatch.setattr(
        "brainpalace_cli.xdg_paths.get_xdg_config_dir", lambda: tmp_path
    )
    return tmp_path / "config.yaml"


def _patch_tty(monkeypatch):
    """Make _stdin_is_tty() return True so the interactive path is exercised."""
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)


def test_init_global_yes_is_noop(monkeypatch, tmp_path):
    gcfg = _patch_xdg(monkeypatch, tmp_path)
    result = CliRunner().invoke(init_command, ["--global", "--yes"])
    assert result.exit_code == 0 and not gcfg.exists()


def test_init_global_json_noop_emits_json(monkeypatch, tmp_path):
    _patch_xdg(monkeypatch, tmp_path)
    result = CliRunner().invoke(init_command, ["--global", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output.strip())["status"] == "noop"  # finding #2


def test_init_global_continue_no_edits_writes_nothing(monkeypatch, tmp_path):
    gcfg = _patch_xdg(monkeypatch, tmp_path)
    _patch_tty(monkeypatch)
    result = CliRunner().invoke(init_command, ["--global"], input="c\nn\n")
    assert result.exit_code == 0, result.output
    assert not gcfg.exists()


def test_init_global_sparse_write(monkeypatch, tmp_path):
    gcfg = _patch_xdg(monkeypatch, tmp_path)
    _patch_tty(monkeypatch)
    runner = CliRunner()
    # Probe: discover the real prompt/menu order (division list + control prompt).
    probe = runner.invoke(init_command, ["--global"], input="c\nn\n")
    assert probe.exit_code == 0, probe.output
    # "c" = Continue with no edits → nothing written (idempotent-accept invariant).
    assert not gcfg.exists(), "Accept with no edits must not write the file"

    # Now drill embedding (division 1), change provider to ollama (option 3),
    # then Enter past all remaining fields (model/api_key/api_key_env/base_url/
    # params), then "c" to continue, then "n" to skip dashboard.
    # Gate-first drill: embedding has no gates. All fields shown (incl. advanced
    # api_key_env and hidden api_key/params).
    result = runner.invoke(init_command, ["--global"], input="1\n3\n\n\n\n\n\nc\nn\n")
    assert result.exit_code == 0, result.output
    assert gcfg.exists(), "Editing a field must write the file"
    written = yaml.safe_load(gcfg.read_text())
    # Sparse write: only the changed dotpath (embedding.provider) is present.
    assert written.get("embedding", {}).get("provider") == "ollama"
    # No other top-level keys written (sparse invariant).
    extra_keys = {k for k in written if k != "embedding"}
    assert not extra_keys, f"Non-sparse write: unexpected keys {extra_keys}"
