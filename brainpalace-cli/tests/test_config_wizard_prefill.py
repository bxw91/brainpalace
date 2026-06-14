"""The `config wizard` seeds prompt defaults from the saved global config.

Re-running the wizard and accepting every default (pressing Enter) must preserve
the previously-saved values, not reset them to shipped defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from brainpalace_cli import commands
from brainpalace_cli.cli import cli

_PREFILL = {
    "embedding": {"provider": "openai", "model": "my-embed-model"},
    "summarization": {"provider": "openai", "model": "my-summ-model"},
    "graphrag": {"enabled": True, "store_type": "sqlite", "use_code_metadata": True},
    "session_indexing": {"enabled": True, "archive": {"enabled": False}},
    "git_indexing": {"enabled": False, "depth": 1234},
    "reranker": {"enabled": False},
    "bm25": {"engine": "stem"},
    "api": {"host": "127.0.0.1", "port": 9099},
    "dashboard": {"autostart": False, "port": 9191},
}


def test_wizard_global_prefills_from_saved_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_mod = commands.config
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    (xdg / "config.yaml").write_text(yaml.safe_dump(_PREFILL))

    monkeypatch.setattr(config_mod, "get_xdg_config_dir", lambda: xdg)
    # Keep the wizard offline + deterministic.
    monkeypatch.setattr(config_mod, "_find_available_api_port", lambda *a, **k: 8000)
    monkeypatch.setattr(config_mod, "_find_config_file", lambda *a, **k: None)

    runner = CliRunner()
    # Accept every default by sending blank lines.
    res = runner.invoke(cli, ["config", "wizard", "--global"], input="\n" * 30)
    assert res.exit_code == 0, res.output

    written = yaml.safe_load((xdg / "config.yaml").read_text())
    assert written["embedding"]["model"] == "my-embed-model"
    assert written["summarization"]["model"] == "my-summ-model"
    assert written["api"]["port"] == 9099
    assert written["dashboard"]["port"] == 9191
    assert written["dashboard"]["autostart"] is False
    assert written["session_indexing"]["enabled"] is True
    assert written["session_indexing"]["archive"]["enabled"] is False
    assert written["git_indexing"]["depth"] == 1234


def test_wizard_global_uses_shipped_defaults_without_prior_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_mod = commands.config
    xdg = tmp_path / "xdg"
    xdg.mkdir()  # no config.yaml present

    monkeypatch.setattr(config_mod, "get_xdg_config_dir", lambda: xdg)
    monkeypatch.setattr(config_mod, "_find_available_api_port", lambda *a, **k: 8055)
    monkeypatch.setattr(config_mod, "_find_config_file", lambda *a, **k: None)

    runner = CliRunner()
    res = runner.invoke(cli, ["config", "wizard", "--global"], input="\n" * 30)
    assert res.exit_code == 0, res.output

    written = yaml.safe_load((xdg / "config.yaml").read_text())
    assert written["embedding"]["provider"] == "openai"  # shipped default
    assert written["api"]["port"] == 8055  # discovered, not prefilled
    assert written["dashboard"]["port"] == 8787
